"""Deterministic checks a deck must pass before it is sent.

The LLM only writes prose, so these checks guard what it can get wrong:
text that no longer fits its box, colours outside the brand palette, a logo
covering text, and claims that cite evidence the retrieval step never returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

from . import render
from .measure import wrapped_height
from .schemas import Proposal

EMU_PER_PX = 9525


@dataclass
class Issue:
    slide: int
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"slide {self.slide:02d} · {self.kind}: {self.detail}"


def check_overflow(path: str) -> list[Issue]:
    issues = []
    for i, slide in enumerate(Presentation(path).slides, start=1):
        for sh in slide.shapes:
            if not sh.has_text_frame or not sh.text_frame.text.strip():
                continue
            runs = [r for p in sh.text_frame.paragraphs for r in p.runs]
            if not runs or runs[0].font.size is None:
                continue
            size_px = runs[0].font.size.pt / 0.75
            spacing = sh.text_frame.paragraphs[0].line_spacing or 1.2
            w = Emu(sh.width) / EMU_PER_PX
            h = Emu(sh.height) / EMU_PER_PX
            need = wrapped_height(sh.text_frame.text, runs[0].font.name, bool(runs[0].font.bold),
                                  size_px, w, spacing)
            gaps = sum((p.space_before.pt / 0.75) if p.space_before else 0
                       for p in sh.text_frame.paragraphs)
            if need + gaps > h * 1.02:  # rounding only; line height is modelled
                issues.append(Issue(i, "overflow",
                                    f"{sh.name}: needs {need + gaps:.0f}px, box is {h:.0f}px "
                                    f"({sh.text_frame.text[:40]!r}…)"))
    return issues


def check_tables(path: str) -> list[Issue]:
    """A cell taller than its row makes LibreOffice and PowerPoint grow the
    row, which pushes the table into whatever sits below it."""
    issues = []
    for i, slide in enumerate(Presentation(path).slides, start=1):
        for sh in slide.shapes:
            if not getattr(sh, "has_table", False):
                continue
            tbl = sh.table
            for ri, row in enumerate(tbl.rows):
                h = Emu(row.height) / EMU_PER_PX
                for ci, cell in enumerate(row.cells):
                    runs = [r for p in cell.text_frame.paragraphs for r in p.runs]
                    if not runs or not cell.text.strip() or runs[0].font.size is None:
                        continue
                    w = (Emu(tbl.columns[ci].width) - Emu(cell.margin_left)
                         - Emu(cell.margin_right)) / EMU_PER_PX
                    need = wrapped_height(cell.text, runs[0].font.name, bool(runs[0].font.bold),
                                          runs[0].font.size.pt / 0.75, w, 1.0)
                    if need > h * 1.02:
                        issues.append(Issue(i, "overflow",
                                            f"table row {ri} col {ci}: needs {need:.0f}px, row is "
                                            f"{h:.0f}px ({cell.text[:40]!r}…)"))
    return issues


def _rect(sh) -> tuple[float, float, float, float]:
    return (sh.left / EMU_PER_PX, sh.top / EMU_PER_PX, (sh.left + sh.width) / EMU_PER_PX,
            (sh.top + sh.height) / EMU_PER_PX)


def check_logo_overlap(path: str) -> list[Issue]:
    """A picture (the logos) must not cover any shape that shows text or a table."""
    issues = []
    for i, slide in enumerate(Presentation(path).slides, start=1):
        pics = [sh for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE]
        texts = [sh for sh in slide.shapes if getattr(sh, "has_table", False)
                 or (sh.has_text_frame and sh.text_frame.text.strip())]
        for p in pics:
            px0, py0, px1, py1 = _rect(p)
            for t in texts:
                tx0, ty0, tx1, ty1 = _rect(t)
                if min(px1, tx1) - max(px0, tx0) > 0.5 and min(py1, ty1) - max(py0, ty0) > 0.5:
                    issues.append(Issue(i, "overlap", f"{p.name} overlaps {t.name} "
                                                      f"({t.text_frame.text[:30]!r})"
                                        if t.has_text_frame else f"{p.name} overlaps {t.name}"))
    return issues


def check_palette(path: str) -> list[Issue]:
    issues = []
    allowed = {str(c) for c in render.PALETTE}
    for i, slide in enumerate(Presentation(path).slides, start=1):
        xml = slide._element.xml
        for val in set(re.findall(r'srgbClr val="([0-9A-F]{6})"', xml)):
            if val not in allowed and not _is_tint(val):
                issues.append(Issue(i, "off-palette colour", f"#{val}"))
    return issues


def _is_tint(hexval: str) -> bool:
    """Table bands, pills and borders use tints of the brand greens and
    amber; accept anything close to the line between a brand colour and
    white or the dark ink."""
    r, g, b = (int(hexval[k:k + 2], 16) for k in (0, 2, 4))
    anchors = [tuple(c) for c in render.PALETTE]
    for a in anchors:
        for c in anchors:
            if a == c:
                continue
            for t in range(0, 21):
                m = [a[k] + (c[k] - a[k]) * t / 20 for k in range(3)]
                if max(abs(m[0] - r), abs(m[1] - g), abs(m[2] - b)) <= 18:
                    return True
    return False


def check_evidence(data: Proposal, retrieved_ids: set[str]) -> list[Issue]:
    """Every id the prose cites must come from this run's retrieval."""
    issues = []
    cited = [(3, e) for p in data.summary.pillars for e in p.evidence]
    cited += [(5, r.evidence_id) for r in data.requirements if r.evidence_id]
    cited += [(7, c.cv_id) for c in data.team if c.cv_id]
    cited += [(8, r.project_id) for r in data.references if r.project_id]
    for slide, ev in cited:
        if ev not in retrieved_ids:
            issues.append(Issue(slide, "unsupported claim", f"{ev} was not retrieved"))
    return issues


def validate(path: str, data: Proposal | None = None,
             retrieved_ids: set[str] | None = None) -> list[Issue]:
    issues = (check_overflow(path) + check_tables(path) + check_palette(path)
              + check_logo_overlap(path))
    if data is not None and retrieved_ids is not None:
        issues += check_evidence(data, retrieved_ids)
    return issues
