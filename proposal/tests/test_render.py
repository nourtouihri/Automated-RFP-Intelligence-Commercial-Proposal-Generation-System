"""The rendered deck and the validator, read back from the .pptx."""

from __future__ import annotations

import dataclasses
import json

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.dml.color import RGBColor
from pptx.util import Emu

from proposal import render
from proposal.compose import TASKS, compose, tasks
from proposal.config import Config
from proposal.schemas import NextStep, NoBid, Proposal, Signatory
from proposal.tests.test_compose import CVS, PRJ, RECORDS, REPLIES, REQ, RESEARCH, TENDER, fake_llm
from proposal.validate import check_overflow, check_palette, check_tables, validate


@pytest.fixture(autouse=True, scope="module")
def website_theme():
    render.apply_theme("website")


@pytest.fixture
def sample():
    with open("proposal/sample_maison_aurele.json", encoding="utf-8") as f:
        return Proposal.model_validate(json.load(f))


def slide_text(path, n):
    return [sh.text_frame.text for sh in Presentation(str(path)).slides[n - 1].shapes if sh.has_text_frame]


def table(path, n):
    for sh in Presentation(str(path)).slides[n - 1].shapes:
        if getattr(sh, "has_table", False):
            return [[c.text for c in row.cells] for row in sh.table.rows]


# ---------- what the slides say ----------

def test_the_matrix_shows_each_requirement_with_its_fit_evidence_and_score(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    rows = table(path, 5)
    assert rows[0] == ["Requirement", "Fit", "Best evidence", "Score"]
    assert rows[1] == ["CRM data unification", "Strong", "Delivered CRM platform, fashion brand", "0.92"]
    assert rows[4] == ["GDPR and data governance", "Strong", "Governance work inside a data platform project", "0.64"]
    assert rows[5] == ["On-site training in Arabic", "Gap", "No matching asset found, flagged for review", "0.31"]
    assert any("Strong ≥ 0.55, Partial ≥ 0.40" in t for t in slide_text(path, 5))


def test_the_team_and_reference_slides_show_what_the_deck_holds(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    team = slide_text(path, 7)
    assert {"Consultant A", "Consultant B", "Consultant C"} <= set(team)
    refs = slide_text(path, 8)
    assert refs.count("Delivered") == 2 and refs.count("Proposed") == 1


# ---------- the validator really objects ----------

def test_the_validator_reports_text_that_overflows_its_box(sample, tmp_path):
    sample.investment.note = "word " * 400
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    assert [i.kind for i in check_overflow(str(path))] == ["overflow"]
    assert any(i.slide == 9 and i.kind == "overflow" for i in validate(str(path)))


def test_the_validator_reports_a_table_cell_taller_than_its_row(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    prs = Presentation(str(path))
    for sh in prs.slides[4].shapes:
        if getattr(sh, "has_table", False):
            sh.table.cell(1, 2).text_frame.paragraphs[0].runs[0].text = "long cell " * 60
    prs.save(str(path))
    issues = check_tables(str(path))
    assert issues and "table row 1 col 2" in issues[0].detail
    assert any("table row" in i.detail for i in validate(str(path)))


def test_the_validator_reports_a_colour_outside_the_palette(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    prs = Presentation(str(path))
    box = prs.slides[0].shapes.add_shape(1, Emu(0), Emu(0), Emu(9525), Emu(9525))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xFF, 0x00, 0xFF)
    prs.save(str(path))
    assert [(i.kind, i.detail) for i in check_palette(str(path))] == [("off-palette colour", "#FF00FF")]
    assert any(i.kind == "off-palette colour" for i in validate(str(path)))


def test_a_clean_deck_passes_every_check(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    assert validate(str(path)) == []


# ---------- placeholders ----------

def test_placeholder_cards_say_nothing_was_found(tmp_path):
    p = compose(TENDER, RESEARCH, REQ, [], [], fake_llm({"summary": [_no_ids()] * 3}), records=RECORDS)
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    assert slide_text(path, 7).count("No match") == 1 and "?" in slide_text(path, 7)
    refs = slide_text(path, 8)
    assert "No match" in refs and "Nothing retrieved" in refs and "No matching project" in refs


def all_text(path):
    out = []
    for s in Presentation(str(path)).slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False):
                out += [c.text for row in sh.table.rows for c in row.cells]
    return out


def test_no_slide_shows_a_bracketed_placeholder(sample, tmp_path):
    bare = compose(TENDER, None, REQ, [], [], fake_llm({"summary": [_no_ids()] * 3}), records=RECORDS)
    for name, deck in (("sample", sample), ("bare", bare)):
        path = tmp_path / f"{name}.pptx"
        render.render(deck, str(path))
        assert [t for t in all_text(path) if "[" in t] == [], name


def _no_ids():
    reply = json.loads(json.dumps(REPLIES["summary"]))
    for pillar in reply["pillars"]:
        pillar["evidence"] = []
    return reply


# ---------- the config object ----------

ACME = Config(company="Acme", company_sentence="Acme, a roofing firm (Lyon)",
              prepared_by="Acme · Roofs", letter_title="Over your head",
              signatory=Signatory(name="Jo", role="Chief of Roofs", contact="jo@acme.test"),
              currency="£", investment_note="A rough guess.",
              next_steps=(NextStep(title="Site visit", detail="Next week"),),
              proposal_footer="{company} writes to {buyer}", research_source="Source: the web",
              matrix_source="Source: {company} files", team_source="Source: Acme staff",
              references_source="Source: Acme jobs")


def test_a_config_changes_every_company_specific_text():
    systems = []

    def llm(system, user):
        systems.append(system)
        step = next(k for k, v in tasks(ACME).items() if system.endswith(v))
        return json.dumps(_no_ids() if step == "summary" else REPLIES[step])
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, llm, records=RECORDS, config=ACME)
    assert all("Acme, a roofing firm (Lyon)" in s and "OliveSoft" not in s for s in systems)
    assert any("a 'Why Acme' line" in s for s in systems)
    assert p.signatory.role == "Chief of Roofs" and p.letter.title == "Over your head"
    assert (p.investment.currency, p.investment.note) == ("£", "A rough guess.")
    assert [s.title for s in p.investment.next_steps] == ["Site visit"]


def test_a_config_changes_the_rendered_footers_and_cover(sample, tmp_path):
    logos = {}
    for name, size in (("logo_lockup", (400, 100)), ("logo_symbol", (80, 100))):
        logos[name] = tmp_path / f"acme_{name}.png"
        Image.new("RGBA", size, (200, 40, 40, 255)).save(logos[name])
    path = tmp_path / "d.pptx"
    render.render(sample, str(path), config=dataclasses.replace(ACME, **logos))
    pics = {sh.name: sh.image.blob for n in (0, 1) for sh in Presentation(str(path)).slides[n].shapes
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE}
    assert pics == {"logo-lockup": logos["logo_lockup"].read_bytes(),
                    "logo-symbol": logos["logo_symbol"].read_bytes()}
    assert "Acme writes to Maison Aurèle · Sample data" in slide_text(path, 2)
    assert "Source: the web" in slide_text(path, 4)[-2]
    assert "Source: Acme files" in slide_text(path, 5)
    assert "Source: Acme staff" in slide_text(path, 7)
    assert "Source: Acme jobs" in slide_text(path, 8)
    cover = slide_text(path, 1)
    assert "Acme · Roofs" in cover and "OliveSoft" not in " ".join(cover)


def test_the_default_config_prints_olivesofts_own_words(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    assert "OliveSoft · Proposal for Maison Aurèle · Sample data" in slide_text(path, 2)
    assert "OliveSoft · Data & AI" in slide_text(path, 1)
    assert "Source: RAG retrieval over the OliveSoft knowledge base" in slide_text(path, 5)
    assert sample.signatory.name == "OliveSoft Sales Team" and sample.investment.currency == "€"
    assert TASKS["summary"].count("'Why OliveSoft'") == 1


def test_without_research_the_buyer_slide_does_not_claim_research(sample, tmp_path):
    path = tmp_path / "d.pptx"
    deck = sample.model_copy(update={"buyer": sample.buyer.model_copy(update={"researched": False})})
    render.render(deck, str(path))
    text = " ".join(slide_text(path, 4))
    assert "What the tender tells us about Maison Aurèle" in text
    assert "research" not in text.replace("research was unavailable", "")


def test_with_research_the_buyer_slide_names_it(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    assert "What our research tells us about Maison Aurèle" in " ".join(slide_text(path, 4))


def test_the_references_note_says_where_delivered_comes_from(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    text = " ".join(slide_text(path, 8))
    assert ("Delivered only where the project record states it, otherwise Unverified; "
            "never from the model") in text
    assert "status field" not in text


def test_a_project_without_a_status_is_shown_unverified(tmp_path):
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS)
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    refs = slide_text(path, 8)
    assert refs.count("Unverified") == 1 and refs.count("Proposed") == 1
    assert "Delivered" not in refs


def test_the_investment_slide_has_no_blanks(tmp_path):
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS)
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    assert "Indicative investment" in slide_text(path, 9)
    assert table(path, 9)[1:] == [["Discover", "20", "€ 13,000"], ["Build", "60", "€ 39,000"],
                                  ["Total", "80", "€ 52,000"]]


def test_the_buyer_slide_has_no_footprint_row(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    text = " ".join(slide_text(path, 4))
    assert "Footprint" not in text and "Sector" in text and "Key partners" in text


# ---------- the warnings slide absorbs long lists ----------

def _no_bid_with(warnings, sample):
    rows = [r.model_copy(update={"score": 0.2, "fit": "Gap"}) for r in sample.requirements]
    return NoBid(meta=sample.meta, requirements=rows, warnings=list(warnings),
                 recommendation="Do not bid.")


def test_a_few_warnings_keep_the_original_roomy_layout(sample, tmp_path):
    deck = _no_bid_with(["no-bid recommendation: every requirement is a Gap",
                         "tender ingest warning: unknown_fields"], sample)
    path = tmp_path / "d.pptx"
    render.render_no_bid(deck, str(path))
    tb = [sh for sh in Presentation(str(path)).slides[2].shapes
          if sh.name == "warnings"][0]
    assert tb.text_frame.paragraphs[0].runs[0].font.size.pt / 0.75 == 19
    assert check_overflow(str(path)) == []


def test_a_many_warning_no_bid_deck_rendering_still_passes_the_validator(sample, tmp_path):
    # The incident that rejected real decks: needs 307px inside a 230px box.
    warnings = ["no-bid recommendation: every requirement is a Gap (best match below 0.40)",
                "tender is marked incomplete: deadline and several fields are missing",
                "tender ingest warnings: unknown_fields, sanitized_chars, excerpted_text",
                "the tender expired 14 days ago; the deadline has already passed",
                "no research exists for this tender: the matrix has no sector context",
                "no delivered reference project matches the tender's key requirements",
                "every matched consultant is a weak match for the required skill set",
                "3 of 12 requirements are hidden because the matrix shows 6 rows only; "
                "4 of the 6 hidden requirements are Gap rows worth a manual review",
                "the pricing model was not calibrated against the tender's budget cap"]
    deck = _no_bid_with([w * 2 for w in warnings], sample)
    path = tmp_path / "d.pptx"
    render.render_no_bid(deck, str(path))
    tb = [sh for sh in Presentation(str(path)).slides[2].shapes
          if sh.name == "warnings"][0]
    assert all("•  " + w[:12] in tb.text_frame.text for w in deck.warnings)  # all kept
    assert check_overflow(str(path)) == []


def test_an_absurdly_long_list_is_ellipsized_but_never_overflows(sample, tmp_path):
    filler = "delivered evidence and scored requirement concern " * 12  # ~600 chars
    deck = _no_bid_with([f"warning {i}: {filler}" for i in range(14)], sample)
    path = tmp_path / "d.pptx"
    render.render_no_bid(deck, str(path))
    tb = [sh for sh in Presentation(str(path)).slides[2].shapes
          if sh.name == "warnings"][0]
    assert tb.text_frame.text.count("•  ") == 14  # every bullet stays on the slide
    assert tb.text_frame.text.count("…") >= 1  # the longest ones are cut, not dropped
    assert check_overflow(str(path)) == []
