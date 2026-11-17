"""Render a Proposal into an OliveSoft-branded 16:9 .pptx.

Layout is drawn in code rather than read from a .potx: the sample deck only
exists as images, and fixed geometry lets the validator know every box's
size. Coordinates are in pixels of the 1280x720 sample, so positions can be
checked against it directly (1 px = 9525 EMU, 1 px of type = 0.75 pt).
"""

from __future__ import annotations

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from .config import DEFAULT, Config
from .measure import fit_text, fits, line_count, line_pitch, wrapped_height
from .schemas import PARTIAL_AT, STRONG_AT, NoBid, Proposal, fit_for

# Palettes. "sample" is sampled from qui's sample deck; "website" from the
# olivesoft.fr screenshots (navy header, mint-grey page, teal accents). Roles,
# not hues, are what the layout code uses, so a theme swap is a palette swap.
THEMES = {
    "sample": dict(INK="17241B", OLIVE="4F7A28", AMBER="DAA442", PAPER="F5F6F0",
                   CARD="FCFDF8", SAGE="E6EED7", LEAF="9CC96B", LINE="E2E4D9",
                   MUTED="5F635B", SOFT_ON_DARK="C8D9BE", RED="A32D22", OCHRE="8A630F",
                   BLOB2="DAA442"),
    # Teal #08DDD8 and mint #3DE1B9 are too light for text on white, so the
    # text accent is a darker teal; the bright tones stay for fills.
    "website": dict(INK="070D20", OLIVE="0B7F86", AMBER="3DE1B9", PAPER="F5F9F8",
                    CARD="FFFFFF", SAGE="EAF4F2", LEAF="3DE1B9", LINE="DDE6E4",
                    MUTED="5B6573", SOFT_ON_DARK="B8C4D6", RED="C0392B", OCHRE="A86A00",
                    BLOB2="0095E4"),
}


def _rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


def mix(a: RGBColor, b: RGBColor, t: float) -> RGBColor:
    """Tint between two palette colours, so derived shades follow the theme."""
    return RGBColor(*(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))


WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def apply_theme(name: str = "sample") -> None:
    g = globals()
    for role, hexval in THEMES[name].items():
        g[role] = _rgb(hexval)
    g["THEME"] = name
    g["FIT_COLOR"] = {"Strong": g["OLIVE"], "Partial": g["OCHRE"], "Gap": g["RED"]}
    g["PALETTE"] = {g[r] for r in THEMES[name]} | {WHITE}


apply_theme("sample")

# Decision O2: Montserrat for headings (closest free match to the site's
# uppercase geometric headings), Inter for body text. Both are free; PDFs embed
# them, but a .pptx needs them installed or PowerPoint substitutes.
FONT = "Inter"
HEAD_FONT = "Montserrat"
TOTAL = 9


def px(v: float) -> Emu:
    return Emu(int(v * 9525))


class LogoError(RuntimeError):
    pass


def check_logos(config: Config) -> dict[str, tuple[int, int]]:
    """Each logo file's pixel size. Raises LogoError naming the file when one is missing
    or cannot be decoded, before any slide exists, so no deck is half-written."""
    sizes = {}
    for path in (config.logo_lockup, config.logo_symbol):
        if not path.is_file():
            raise LogoError(f"logo file not found: {path}")
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:  # verify() leaves the image unusable; decode it fully
                im.load()
                sizes[str(path)] = im.size
        except Exception as e:  # Pillow raises several types for a bad file
            raise LogoError(f"logo file is not a readable image: {path} ({e})") from None
    return sizes


class Deck:
    def __init__(self, data: Proposal | NoBid, font: str = FONT, head_font: str = HEAD_FONT,
                 config: Config = DEFAULT, total: int = TOTAL):
        self.d = data
        self.font = font
        self.head_font = head_font
        self.config = config
        self.total = total
        self.logo_sizes = check_logos(config)
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = px(1280), px(720)
        self.blank = self.prs.slide_layouts[6]

    # ---------- primitives ----------

    def slide(self, bg: RGBColor):
        s = self.prs.slides.add_slide(self.blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = bg
        return s

    def box(self, s, x, y, w, h, fill=None, line=None, radius=12, shape=None, dash=False):
        kind = shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE)
        sh = s.shapes.add_shape(kind, px(x), px(y), px(w), px(h))
        if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
            sh.adjustments[0] = radius / min(w, h)
        if fill is None:
            sh.fill.background()
        else:
            sh.fill.solid()
            sh.fill.fore_color.rgb = fill
        if line is None:
            sh.line.fill.background()
        else:
            sh.line.color.rgb = line
            sh.line.width = Pt(0.75)
            if dash:
                sh.line.dash_style = 4  # MSO_LINE.DASH
        # The default <p:style> references the theme's shadow effect, which
        # LibreOffice renders even with an empty effectLst; the brand is flat.
        style = sh._element.find(qn("p:style"))
        if style is not None:
            sh._element.remove(style)
        sh.text_frame.text = ""
        return sh

    def text(self, s, x, y, w, h, runs, size=16, color=None, bold=False, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, spacing=None, line_spacing=1.2, para_gap=0, name=None, head=False,
             truncate=False):
        """runs: a string, or a list of paragraphs; a paragraph is a string or
        a list of (text, overrides) tuples.

        Every box autofits: the font shrinks to 80% when the text is too long.
        truncate=True (data-driven text only, never LLM prose) then cuts whole
        words with an ellipsis; LLM prose is kept short by the schema limits."""
        color = color or INK
        face = self.head_font if head else self.font
        if isinstance(runs, str):
            runs, size = fit_text(runs, face, bold, size, w, h, line_spacing, truncate=truncate)
        else:
            joined = "\n".join(p if isinstance(p, str) else "".join(t for t, _ in p) for p in runs)
            gaps = para_gap / 0.75 * (len(runs) - 1)
            _, size = fit_text(joined, face, bold, size, w, h - gaps, line_spacing)
        tb = s.shapes.add_textbox(px(x), px(y), px(w), px(h))
        if name:
            tb.name = name
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = anchor
        paras = [runs] if isinstance(runs, str) else runs
        for i, para in enumerate(paras):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            p.line_spacing = line_spacing
            if i and para_gap:
                p.space_before = Pt(para_gap)
            for txt, over in ([(para, {})] if isinstance(para, str) else para):
                r = p.add_run()
                r.text = txt
                f = r.font
                f.name = face
                f.size = Pt(over.get("size", size) * 0.75)
                f.bold = over.get("bold", bold)
                f.color.rgb = over.get("color", color)
                sp = over.get("spacing", spacing)
                if sp:
                    r._r.get_or_add_rPr().set("spc", str(int(sp * 100)))
        return tb

    def kicker(self, s, n, label, color=None, y=88):
        self.text(s, 86, y, 900, 22, f"{n:02d} · {label.upper()}", size=15, bold=True,
                  color=color or OLIVE, spacing=1.6, name="kicker", head=True)

    def title(self, s, t, color=None):
        self.text(s, 86, 116, 1110, 56, t, size=40, bold=True, color=color, line_spacing=1.0,
                  name="title", head=True, truncate=True)

    def footer(self, s, n, dark=False, left=None):
        d = self.d.meta
        col = LEAF if dark else MUTED
        c = self.config
        left = left or (c.proposal_footer.format(company=c.company, buyer=d.buyer)
                        + (" · Sample data" if d.sample else ""))
        # Data-driven text is cut with an ellipsis, so a long buyer name never overflows.
        self.text(s, 86, 656, 900, 20, left, size=15, color=col, name="footer", truncate=True)
        self.text(s, 1000, 656, 160, 20, f"{n:02d} / {self.total:02d}", size=15, color=col,
                  align=PP_ALIGN.RIGHT, name="page")
        # The symbol sits right of the page number, centred on the footer line, its right
        # edge on the 1195 px margin; its gradient reads on both light and dark slides.
        self.logo(s, self.config.logo_symbol, 1195, 652, 28, "logo-symbol", right=True)

    def logo(self, s, path, x, y, h, name, right=False):
        iw, ih = self.logo_sizes[str(path)]
        w = h * iw / ih
        pic = s.shapes.add_picture(str(path), px(x - w if right else x), px(y), px(w), px(h))
        pic.name = name
        return pic

    def pill(self, s, x, y, label, fill, color, w=None, h=32):
        w = w or 18 + len(label) * 8.6
        b = self.box(s, x, y, w, h, fill=fill, radius=h / 2)
        self.text(s, x, y, w, h, label, size=15, bold=True, color=color, align=PP_ALIGN.CENTER,
                  anchor=MSO_ANCHOR.MIDDLE)
        return b

    def table(self, s, x, y, widths, rows, head_fill, head_color, body_fills, body_color,
              border, row_h=38, aligns=None, cell_colors=None, total_fill=None, max_lines=2):
        """Rows grow to the measured text, up to max_lines; longer cell text is
        cut with an ellipsis. Returns the table's total height in px."""
        size, pad = 17, 11
        pitch = line_pitch(self.font, False, size)
        heights = []
        for i, row in enumerate(rows):
            lines = 1
            for j, val in enumerate(row):
                inner = widths[j] - 2 * pad
                val, _ = fit_text(val, self.font, i == 0, size, inner, max_lines * pitch,
                                  line_spacing=1.0, min_scale=1.0, truncate=True)
                row[j] = val
                lines = max(lines, line_count(val, self.font, i == 0, size, inner))
            heights.append(max(row_h, lines * pitch + 12))
        shape = s.shapes.add_table(len(rows), len(widths), px(x), px(y), px(sum(widths)),
                                   px(sum(heights)))
        tbl = shape.table
        # Drop the default theme style so only our fills show.
        tbl._tbl.tblPr.set("firstRow", "0")
        tbl._tbl.tblPr.set("bandRow", "0")
        for j, w in enumerate(widths):
            tbl.columns[j].width = px(w)
        for i, row in enumerate(rows):
            tbl.rows[i].height = px(heights[i])
            is_total = total_fill is not None and i == len(rows) - 1
            for j, val in enumerate(row):
                c = tbl.cell(i, j)
                c.fill.solid()
                c.fill.fore_color.rgb = (head_fill if i == 0 else total_fill if is_total
                                         else body_fills[(i - 1) % len(body_fills)])
                c.margin_left = c.margin_right = px(11)
                c.margin_top = c.margin_bottom = 0
                c.vertical_anchor = MSO_ANCHOR.MIDDLE
                self._cell_border(c, border)
                p = c.text_frame.paragraphs[0]
                p.alignment = (aligns or [PP_ALIGN.LEFT] * len(widths))[j]
                r = p.add_run()
                r.text = val
                r.font.name = self.font
                r.font.size = Pt(17 * 0.75)
                r.font.bold = i == 0
                color = head_color if i == 0 else body_color
                if i and cell_colors and (i, j) in cell_colors:
                    color = cell_colors[(i, j)]
                r.font.color.rgb = color
        return sum(heights)

    @staticmethod
    def _cell_border(cell, rgb):
        tcPr = cell._tc.get_or_add_tcPr()
        for edge in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
            ln = tcPr.find(qn(edge))
            if ln is None:
                ln = tcPr.makeelement(qn(edge), {})
                tcPr.append(ln)
            ln.set("w", "9525")
            fill = ln.makeelement(qn("a:solidFill"), {})
            clr = fill.makeelement(qn("a:srgbClr"), {"val": str(rgb)})
            fill.append(clr)
            ln.append(fill)

    # ---------- slides ----------

    def cover(self, kicker="COMMERCIAL PROPOSAL"):
        d = self.d.meta
        s = self.slide(INK)
        # The lockup's wordmark is white, made for this dark cover; it replaces the
        # text wordmark at the same place.
        self.logo(s, self.config.logo_lockup, 86, 64, 40, "logo-lockup")
        self.box(s, 787, 93, 413, 413, fill=OLIVE, shape=MSO_SHAPE.OVAL)
        self.box(s, 1000, 346, 173, 173, fill=BLOB2, shape=MSO_SHAPE.OVAL)
        kicker = kicker + (" · SAMPLE" if d.sample else "")
        self.text(s, 86, 220, 700, 22, kicker, size=15, bold=True, color=AMBER, spacing=2.2)
        self.text(s, 86, 262, 760, 140, d.headline, size=54, bold=True, color=PAPER,
                  line_spacing=1.05, name="title", head=True)
        self.text(s, 86, 410, 760, 34, d.subtitle, size=23, color=SOFT_ON_DARK)
        line = s.shapes.add_connector(1, px(86), px(556), px(1195), px(556))
        line.line.color.rgb = mix(INK, PAPER, 0.12)
        for x, w, label, value in [(86, 330, "Prepared for", d.buyer),
                                   (427, 220, "Prepared by", self.config.prepared_by),
                                   (655, 540, "Date · Reference", f"{d.date} · {d.reference}")]:
            self.text(s, x, 580, w, 20, label, size=16, color=LEAF)
            self.text(s, x, 608, w, 52, value, size=20, color=PAPER, truncate=True)

    def letter(self, n=2):
        L, sig = self.d.letter, self.d.signatory
        s = self.slide(PAPER)
        self.kicker(s, n, "Cover letter")
        self.title(s, L.title)
        self.box(s, 86, 195, 689, 345, fill=CARD, line=LINE)
        paras = [[(L.salutation, {"color": INK})]] + [[(p, {})] for p in L.paragraphs] + \
                [[(L.closing, {"color": INK})]]
        self.text(s, 118, 228, 625, 290, paras, size=20, color=MUTED, para_gap=9,
                  line_spacing=1.3, name="letter-body")
        self.box(s, 818, 195, 377, 345, fill=INK)
        self.text(s, 850, 228, 320, 22, "SIGNED", size=15, bold=True, color=AMBER, spacing=1.6)
        self.text(s, 850, 420, 320, 30, sig.name, size=25, bold=True, color=PAPER)
        self.text(s, 850, 458, 320, 22, sig.role, size=16, color=SOFT_ON_DARK)
        self.text(s, 850, 486, 320, 22, sig.contact, size=16, color=SOFT_ON_DARK)
        self.footer(s, n)

    def summary(self, n=3):
        S = self.d.summary
        s = self.slide(SAGE)
        self.kicker(s, n, "Executive summary")
        self.title(s, S.title)
        for i, p in enumerate(S.pillars):
            x = 86 + i * 377
            self.box(s, x, 195, 355, 245, fill=CARD)
            self.text(s, x + 27, 220, 300, 60, f"{i + 1:02d}", size=58, bold=True, color=OLIVE, head=True,
                      line_spacing=1.0)
            self.text(s, x + 27, 290, 300, 30, p.title, size=22, bold=True)
            self.text(s, x + 27, 330, 290, 95, p.body, size=18, color=MUTED, line_spacing=1.3,
                      name="pillar-body")
        self.box(s, 86, 473, 1109, 98, fill=AMBER)
        self.text(s, 112, 473, 1060, 98, S.why_us, size=19, anchor=MSO_ANCHOR.MIDDLE,
                  line_spacing=1.3, name="why-us")
        self.footer(s, n)

    def buyer(self, n=4):
        B = self.d.buyer
        s = self.slide(PAPER)
        self.kicker(s, n, "Understanding of the buyer")
        self.title(s, f"What {'our research' if B.researched else 'the tender'} tells us about "
                      f"{self.d.meta.buyer}")
        self.box(s, 86, 195, 373, 390, fill=INK)
        self.text(s, 118, 228, 320, 22, "PROFILE", size=15, bold=True, color=AMBER, spacing=1.6)
        pr = B.profile
        for i, (key, label) in enumerate([("sector", "Sector"),
                                          ("estimated_revenue", "Estimated revenue"),
                                          ("key_partners", "Key partners")]):
            y = 268 + i * 72
            value = getattr(pr, key)
            if f"buyer.profile.{key}" in self.d.estimated:
                # an estimated revenue holds the size the tender states (estimate_size)
                label = "Size (est.)" if key == "estimated_revenue" else f"{label} (est.)"
            self.text(s, 118, y, 320, 20, label, size=16, color=LEAF)
            self.text(s, 118, y + 26, 320, 28, value, size=20, color=PAPER, name="profile-value", truncate=True)
        n_needs = len(B.needs)
        gap, top, bottom = 16, 195, 585
        h = (bottom - top - gap * (n_needs - 1)) / n_needs
        for i, need in enumerate(B.needs):
            y = top + i * (h + gap)
            self.box(s, 491, y, 704, h, fill=CARD, line=LINE)
            self.text(s, 516, y + 22, 650, 30, need.title, size=23, bold=True)
            self.text(s, 516, y + 58, 650, h - 70, need.body, size=19, color=MUTED,
                      line_spacing=1.3, name="need-body")
        self.footer(s, n, left=self.config.research_source if B.researched
                    else self.config.no_research_source)

    def matrix(self, n=5):
        rows = [["Requirement", "Fit", "Best evidence", "Score"]]
        colors = {}
        for i, r in enumerate(self.d.requirements, start=1):
            fit = fit_for(r.score)
            evidence = r.evidence if r.evidence_id else "No matching asset found, flagged for review"
            rows.append([r.requirement, fit, evidence, f"{r.score:.2f}"])
            colors[(i, 1)] = colors[(i, 3)] = FIT_COLOR[fit]
        s = self.slide(CARD)
        self.kicker(s, n, "Requirements matrix")
        self.title(s, "How our assets match your requirements")
        height = self.table(s, 86, 190, [377, 155, 421, 156], rows, INK, PAPER,
                            [CARD, mix(CARD, OLIVE, 0.07)], INK, mix(CARD, INK, 0.2),
                            aligns=[PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.RIGHT],
                            cell_colors=colors)
        # A full table ends at 620 px at most; the note stays above the footer (656) and left of
        # the logo symbol (1173).
        y = min(190 + height + 18, 630)
        self.text(s, 86, y, 1060, 22, "Score = semantic retrieval similarity between the tender "
                  f"requirement and the best indexed asset (0 to 1). Strong ≥ {STRONG_AT:.2f}, "
                  f"Partial ≥ {PARTIAL_AT:.2f}.",
                  size=15, color=MUTED)
        self.footer(s, n, left=self.config.matrix_source.format(company=self.config.company))

    def approach(self, n=6):
        A = self.d.approach
        s = self.slide(SAGE)
        self.kicker(s, n, "Approach and timeline")
        self.title(s, A.title)
        accents = [OLIVE, AMBER, INK, OLIVE]
        labels = [OLIVE, OCHRE, INK, OLIVE]
        total_w, gap = 1109, 22
        # Equal columns: sizing by weeks left a 1-week phase too narrow for its text.
        w = (total_w - gap * (len(A.phases) - 1)) / len(A.phases)
        x, start = 86.0, 1
        for i, p in enumerate(A.phases):
            self.box(s, x, 189, w, 204, fill=CARD, radius=8)
            self.box(s, x, 189, w, 6, fill=accents[i], radius=0)
            end = start + p.weeks - 1
            self.text(s, x + 25, 220, w - 45, 22, f"Weeks {start} to {end}", size=16, bold=True,
                      color=labels[i])
            self.text(s, x + 25, 250, w - 45, 30, p.name, size=23, bold=True)
            self.text(s, x + 25, 286, w - 45, 102, p.body, size=19, color=MUTED, line_spacing=1.3,
                      name="phase-body")
            self.box(s, x, 420, w, 43, fill=accents[i], radius=5)
            self.text(s, x, 420, w, 43, f"{p.weeks} wk", size=16, bold=True,
                      color=INK if accents[i] == AMBER else PAPER, align=PP_ALIGN.CENTER,
                      anchor=MSO_ANCHOR.MIDDLE)
            x += w + gap
            start = end + 1
        self.text(s, 86, 490, 1100, 22, A.milestones, size=16, color=OLIVE)
        self.footer(s, n)

    def team(self, n=7):
        s = self.slide(PAPER)
        self.kicker(s, n, "Team")
        self.title(s, "Consultants matched to your requirements")
        fills = [(OLIVE, PAPER), (AMBER, INK), (INK, PAPER)]
        for i, c in enumerate(self.d.team):
            x = 86 + i * 377
            self.box(s, x, 195, 355, 252, fill=CARD, line=LINE)
            f, fc = fills[i]
            self.box(s, x + 27, 222, 64, 64, fill=f, shape=MSO_SHAPE.OVAL)
            none = c.cv_id is None  # a placeholder: no CV was retrieved
            initials = "?" if none else "".join(w[0] for w in c.name.split()[:2]).upper()
            self.text(s, x + 27, 222, 64, 64, initials, size=22, bold=True, color=fc,
                      align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            strong = fit_for(c.score) == "Strong"
            self.pill(s, x + 104, 238, "No match" if none else f"Match {c.score:.2f}",
                      mix(CARD, OLIVE, 0.14) if strong else mix(CARD, OCHRE, 0.18),
                      OLIVE if strong else OCHRE)
            self.text(s, x + 27, 296, 300, 30, c.name, size=23, bold=True)
            role = f"{c.years} years · {c.role}" if c.years else c.role
            self.text(s, x + 27, 336, 300, 26, role, size=19, color=MUTED, truncate=True)
            self.text(s, x + 27, 374, 290, 60, c.skills, size=15, color=MUTED, line_spacing=1.3,
                      name="skills", truncate=True)
        self.footer(s, n, left=self.config.team_source)

    def references(self, n=8):
        s = self.slide(CARD)
        self.kicker(s, n, "References")
        self.title(s, "Projects that prove we can do this")
        for i, r in enumerate(self.d.references):
            x = 86 + i * 377
            none = r.project_id is None  # a placeholder: no project was retrieved
            self.box(s, x, 195, 355, 254, fill=PAPER if r.delivered else mix(CARD, OCHRE, 0.05),
                     line=LINE if r.delivered else AMBER, dash=not r.delivered)
            if r.delivered:
                self.pill(s, x + 27, 222, "Delivered", OLIVE, PAPER, w=102)
            elif none:
                self.pill(s, x + 27, 222, "No match", mix(CARD, OCHRE, 0.18), OCHRE, w=102)
            elif r.delivered is None:
                self.pill(s, x + 27, 222, "Unverified", mix(CARD, OCHRE, 0.18), OCHRE, w=102)
            else:
                self.pill(s, x + 27, 222, "Proposed", AMBER, INK, w=102)
            self.text(s, x + 27, 266, 300, 62, r.title, size=23, bold=True, line_spacing=1.15,
                      name="ref-title", truncate=True)
            self.text(s, x + 27, 334, 300, 60, r.summary, size=19, color=MUTED, line_spacing=1.3,
                      name="ref-summary", truncate=True)
            tail = "Not yet delivered" if r.delivered is False else r.sector
            self.text(s, x + 27, 402, 300, 22,
                      "Nothing retrieved" if none else f"Match {r.score:.2f} · {tail}", size=15,
                      color=MUTED)
        self.text(s, 86, 484, 1100, 22, "Delivered only where the project record states it, "
                  "otherwise Unverified; never from the model.", size=16, color=INK)
        self.footer(s, n, left=self.config.references_source)

    def investment(self, n=9):
        I = self.d.investment
        s = self.slide(INK)
        self.kicker(s, n, "Investment and next steps", color=AMBER)
        self.title(s, "Indicative investment", color=PAPER)

        def fmt(v, money=False):
            if v is None:
                return "On request" if money else "–"
            return f"{I.currency} {v:,.0f}" if money else f"{v:g}"

        rows = [["Workstream", "Days", "Amount (excl. VAT)"]]
        rows += [[l.workstream, fmt(l.days), fmt(l.amount, True)] for l in I.lines]
        known = [l for l in I.lines if l.days is not None and l.amount is not None]
        all_known = len(known) == len(I.lines)
        rows.append(["Total",
                     fmt(sum(l.days for l in known) if all_known else None),
                     fmt(sum(l.amount for l in known) if all_known else None, True)])
        dark2 = mix(INK, PAPER, 0.06)
        height = self.table(s, 86, 195, [246, 110, 258], rows, mix(INK, OLIVE, 0.35), AMBER,
                            [dark2, mix(INK, PAPER, 0.03)], PAPER, mix(INK, PAPER, 0.25),
                            aligns=[PP_ALIGN.LEFT, PP_ALIGN.RIGHT, PP_ALIGN.RIGHT],
                            total_fill=OLIVE)
        y = 195 + height + 16
        self.text(s, 86, y, 560, 50, I.note, size=16, color=SOFT_ON_DARK, line_spacing=1.3)
        h = 60 + 70 * len(I.next_steps)
        self.box(s, 732, 195, 463, h, fill=PAPER)
        self.text(s, 759, 222, 400, 22, "NEXT STEPS", size=15, bold=True, color=OLIVE,
                  spacing=1.6)
        for i, st in enumerate(I.next_steps):
            y = 260 + i * 70
            self.text(s, 759, y, 410, 28, f"{i + 1}. {st.title}", size=20, bold=True)
            self.text(s, 759, y + 32, 410, 22, st.detail, size=15, color=MUTED)
        self.footer(s, n, dark=True)

    def warnings(self, n=3):
        d = self.d
        s = self.slide(PAPER)
        self.kicker(s, n, "Bid warnings")
        self.title(s, "Why we recommend not bidding")
        self.box(s, 86, 195, 1109, 280, fill=CARD, line=LINE)
        bullets, size, gap, spacing, y = self._fit_bullets(list(d.input_warnings))
        n = len(bullets)
        self.text(s, 118, y, 1045, 465 - y, [[("•  " + w, {})] for w in bullets], size=size,
                  color=INK, para_gap=gap, line_spacing=spacing, name="warnings")
        self.box(s, 86, 495, 1109, 130, fill=INK)
        self.text(s, 118, 505, 1045, 110, d.recommendation, size=20, color=PAPER, line_spacing=1.3,
                  anchor=MSO_ANCHOR.MIDDLE, name="recommendation")
        self.footer(s, n)

    # The warnings list is the one element whose length is entirely
    # data-driven, and the roomy original layout (19px type, 9px gaps, list
    # starting at y=222) overflowed whenever a tender carried many warnings,
    # which made the validator reject the whole deck. The slide now adapts:
    # a ladder of layouts, roomy to compact, is measured before drawing and
    # the first one that fits is drawn.
    WARN_LADDER = (  # (size, para gap, line spacing, list-top y) inside the card
        (19, 9, 1.30, 222), (17, 6, 1.20, 216), (15, 4, 1.10, 212), (13, 2, 1.05, 208))

    def _fit_bullets(self, bullets: list[str]) -> tuple[list[str], float, float, float, float]:
        """Choose the ladder run that fits the bullets, so nothing is
        truncated until it must be. When even the compact run overflows, the
        tallest bullets are cut with fit_text's whole-word ellipsis — each
        bullet keeps its own leading and a visible tail instead of being
        dropped. Returns (bullets, size, gap, spacing, list-top y)."""
        w = 1045
        for size, gap, spacing, top in self.WARN_LADDER:
            h = 465 - top
            joined = "\n".join("•  " + b for b in bullets)
            # The gap the validator adds (gap * (n - 1)) is charged here the
            # same way text() charges it, so the check and the draw agree.
            if fits(joined, self.font, False, size, w,
                    h - gap * (len(bullets) - 1), spacing):
                return bullets, size, gap, spacing, top
        size, gap, spacing, top = self.WARN_LADDER[-1]
        h = 465 - top
        height = [wrapped_height("•  " + b, self.font, False, size, w, spacing)
                  for b in bullets]
        pitch = line_pitch(self.font, False, size, spacing)
        for _ in range(len(bullets) * 40 + 8):
            # A pass removes at least a whole line from one bullet, so the
            # loop is bounded by the list's line count.
            if sum(height) + gap * (len(bullets) - 1) <= h:
                break
            i = max(range(len(bullets)), key=lambda k: height[k])
            limit = max(height[i] - (sum(height) + gap * (len(bullets) - 1) - h),
                        pitch - 0.1)
            bullets[i] = fit_text("•  " + bullets[i], self.font, False, size, w, limit,
                                  spacing, min_scale=1.0, truncate=True)[0][3:]
            height[i] = min(wrapped_height("•  " + bullets[i], self.font, False, size, w,
                                           spacing), limit)
        return bullets, size, gap, spacing, top

    def build_no_bid(self) -> Presentation:
        self.cover(kicker="NO-BID RECOMMENDATION")
        self.matrix(2)
        self.warnings(3)
        return self.prs

    def build(self) -> Presentation:
        self.cover()
        for step in (self.letter, self.summary, self.buyer, self.matrix, self.approach,
                     self.team, self.references, self.investment):
            step()
        return self.prs


def render(data: Proposal, path: str, font: str = FONT, head_font: str = HEAD_FONT,
           config: Config = DEFAULT) -> str:
    Deck(data, font, head_font, config).build().save(path)
    return path


def render_no_bid(data: NoBid, path: str, font: str = FONT, head_font: str = HEAD_FONT,
                  config: Config = DEFAULT) -> str:
    """Three slides: cover, requirements matrix, bid warnings with the recommendation."""
    Deck(data, font, head_font, config, total=3).build_no_bid().save(path)
    return path
