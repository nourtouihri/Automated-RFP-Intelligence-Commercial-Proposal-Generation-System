"""Formula estimates for facts the inputs lack; a reviewer re-checks every one."""

from __future__ import annotations

import pytest

from proposal import render
from proposal.compose import bid_warnings, compose
from proposal.estimate import estimate_partners, estimate_sector, estimate_size
from proposal.tests.test_compose import CVS, PRJ, RECORDS, REQ, RESEARCH, TENDER, fake_llm
from proposal.tests.test_facts import quiet_summary
from proposal.tests.test_render import slide_text


def tender(issuer="Acme", title="Data platform", text=""):
    return {"issuer": issuer, "title": title, "raw_text": text, "requirements": ["x"]}


@pytest.mark.parametrize("t,sector", [
    (tender("Northgate Regional Health Authority"), "Healthcare"),
    (tender("Meridian Consumer Goods Group"), "Consumer goods"),
    (tender("Sonede", text="The national water operator."), "Utilities"),
    (tender("Ministry of Finance"), "Public sector"),
    (tender("Acme"), "Cross-sector"),
])
def test_sector_comes_from_the_issuer_then_the_tender_text(t, sector):
    assert estimate_sector(t) == sector


@pytest.mark.parametrize("text,size", [
    ("HR data for 4,200 employees across 11 countries.", "Large: 4,200 staff, 11 countries"),
    ("A team of 120 staff.", "SME: 120 staff"),
    ("It runs eleven hospitals on four record systems.", "11 hospitals"),
    ("Catering across four hospital sites.", "4 hospital sites"),
    ("Offices in 3 countries.", "3 countries"),
    ("No size given.", "Size not stated in the tender"),
])
def test_size_is_read_from_the_tender_with_the_eu_band_for_headcount(text, size):
    assert estimate_size(tender(text=text)) == size


def test_partners_are_the_known_systems_the_tender_names_in_order():
    t = tender(text="We run MuleSoft and SAP SuccessFactors with Master Data Management.")
    vocab = ["SAP SuccessFactors", "MuleSoft", "Master Data Management", "Airflow"]
    assert estimate_partners(t, vocab) == "MuleSoft, SAP SuccessFactors"
    assert estimate_partners(tender(text="Nothing named."), vocab) == "None named in the tender"


def test_without_research_every_profile_field_is_estimated_and_listed():
    t = {**TENDER, "issuer": "Sonede water utility", "raw_text": "Airflow pipelines for 900 staff."}
    p = compose(t, None, REQ, CVS, PRJ, fake_llm(), records=RECORDS)
    pr = p.buyer.profile
    assert (pr.sector, pr.estimated_revenue, pr.key_partners) == ("Utilities", "Large: 900 staff",
                                                                  "Airflow")
    assert p.estimated == ["buyer.profile.sector", "buyer.profile.estimated_revenue",
                           "buyer.profile.key_partners", "investment.lines"]
    assert ("research unavailable (no research result): the buyer profile is estimated "
            "from the tender") in bid_warnings(p)


def test_research_values_are_kept_and_only_the_gaps_are_estimated():
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS)
    assert p.buyer.profile.sector == "Water utility"
    assert p.buyer.profile.key_partners == "Ministry of Agriculture"
    assert p.estimated == ["buyer.profile.estimated_revenue", "investment.lines"]


def test_no_cv_gives_a_to_be_staffed_card_for_the_best_requirement():
    p = compose(TENDER, RESEARCH, REQ, [], PRJ, fake_llm({"summary": quiet_summary()}),
                records=RECORDS)
    c = p.team[0]
    assert (c.cv_id, c.name, c.role) == (None, "To be staffed", "Consultant for ETL pipelines")
    assert "team[0]" in p.estimated


def test_the_slide_marks_each_estimated_field(tmp_path):
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS)
    render.apply_theme("website")
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    text = slide_text(path, 4)
    assert "Sector" in text and "Size (est.)" in text and "Key partners" in text
    assert "Estimated revenue" not in text


def test_a_researched_revenue_keeps_its_label(tmp_path):
    p = compose(TENDER, {**RESEARCH, "estimated_revenue": "EUR 40M"}, REQ, CVS, PRJ, fake_llm(),
                records=RECORDS)
    render.apply_theme("website")
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    assert "Estimated revenue" in slide_text(path, 4) and "EUR 40M" in slide_text(path, 4)
