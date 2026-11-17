"""The phase2 contract: an `incomplete` tender and research that is missing, failed or not completed."""

import pytest

from proposal.compose import UNKNOWN, InputError, bid_warnings, compose
from proposal.schemas import NoBid
from proposal.tests.test_compose import CVS, PRJ, RECORDS, REQ, TENDER, fake_llm, hit

DONE = {"tender_id": "tender-001", "issuer": "Sonede", "sector": "Water utility",
        "estimated_revenue": "EUR 40M", "past_projects": ["SCADA upgrade"],
        "key_partners": ["Ministry of Agriculture"], "notes": "", "confidence": "medium",
        "sources": ["https://example.org"], "status": "complete",
        "completed_at": "2026-10-19T09:00:00+00:00"}
INCOMPLETE = {**TENDER, "status": "incomplete", "raw_text": "", "deadline": None,
              "quality": {"completeness": 0.55, "missing_fields": ["raw_text", "deadline"],
                          "warnings": ["no_raw_text"], "is_expired": False}}


def run(tender=TENDER, research=DONE, req=REQ, calls=None):
    return compose(tender, research, req, CVS, PRJ, fake_llm(calls=calls), records=RECORDS)


def research_payload(calls):
    return next(pl for step, pl in calls if step == "brief")["RESEARCH"]


# ---------- the incomplete tender ----------

def test_an_incomplete_tender_with_title_issuer_and_a_requirement_gives_a_deck_with_a_warning():
    p = run(tender=INCOMPLETE)
    assert "tender is incomplete: missing raw_text, deadline" in bid_warnings(p)


def test_an_incomplete_tender_without_missing_fields_names_its_completeness():
    tender = {**INCOMPLETE, "quality": {"completeness": 0.3, "missing_fields": []}}
    assert "tender is incomplete: completeness 0.30" in bid_warnings(run(tender=tender))


@pytest.mark.parametrize("change", [{"title": ""}, {"issuer": None}])
def test_an_incomplete_tender_without_title_or_issuer_is_an_input_error(change):
    with pytest.raises(InputError):
        run(tender={**INCOMPLETE, **change})


def test_an_incomplete_tender_without_requirements_is_an_input_error():
    with pytest.raises(InputError, match="no requirements"):
        run(tender={**INCOMPLETE, "requirements": []}, req={})


def test_a_complete_tender_raises_no_incomplete_warning():
    assert not any("incomplete" in w for w in bid_warnings(run(tender={**TENDER, "status": "new"})))


def test_the_no_bid_deck_carries_the_incomplete_warning_too():
    weak = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.2)]}
    p = run(tender=INCOMPLETE, req=weak)
    assert isinstance(p, NoBid) and "tender is incomplete: missing raw_text, deadline" in bid_warnings(p)


# ---------- research ----------

UNAVAILABLE = {**DONE, "sector": "Water utility", "estimated_revenue": None, "past_projects": [],
               "key_partners": [], "notes": "Skipped: tender deadline has passed",
               "status": "unavailable"}


@pytest.mark.parametrize("research,reason", [
    (None, "no research result"),
    (UNAVAILABLE, "research status is unavailable"),
    ({**DONE, "completed_at": None}, "research has not completed"),
    ({**DONE, "status": "running"}, "research status is running"),
    ({"error": {"code": "UPSTREAM_UNAVAILABLE", "message": "x", "retryable": True}},
     "research failed: UPSTREAM_UNAVAILABLE"),
    ({"detail": "Tender not found"}, "research failed: Tender not found"),
    ("not an object", "research result is not an object"),
])
def test_unusable_research_gives_estimated_buyer_facts_and_a_warning(research, reason):
    calls = []
    p = run(research=research, calls=calls)
    assert {"buyer.profile.sector", "buyer.profile.estimated_revenue",
            "buyer.profile.key_partners"} <= set(p.estimated)
    assert UNKNOWN not in {p.buyer.profile.sector, p.buyer.profile.estimated_revenue}
    assert (f"research unavailable ({reason}): the buyer profile is estimated from the tender"
            in bid_warnings(p))
    assert set(research_payload(calls).values()) == {None}


def test_completed_research_fills_the_buyer_slide_and_raises_no_warning():
    calls = []
    p = run(calls=calls)
    assert (p.buyer.profile.sector, p.buyer.profile.estimated_revenue) == ("Water utility", "EUR 40M")
    assert not any("research" in w for w in bid_warnings(p))
    assert research_payload(calls)["sector"] == "Water utility"


def test_partial_research_is_used_for_what_it_found():
    p = run(research={**DONE, "status": "partial", "estimated_revenue": None})
    assert (p.buyer.profile.sector, p.buyer.profile.estimated_revenue) == ("Water utility", "Size not stated in the tender")
    assert "buyer.profile.estimated_revenue" in p.estimated and "buyer.profile.sector" not in p.estimated
    assert not any("research unavailable" in w for w in bid_warnings(p))


def test_research_shaped_as_on_main_without_a_status_is_used():
    main_shape = {k: v for k, v in DONE.items() if k not in ("status", "completed_at")}
    p = run(research=main_shape)
    assert p.buyer.profile.sector == "Water utility"
    assert not any("research unavailable" in w for w in bid_warnings(p))


def test_the_no_bid_deck_carries_the_research_warning_too():
    weak = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.2)]}
    p = run(research=None, req=weak)
    assert any(w.startswith("research unavailable (no research result)") for w in bid_warnings(p))


def test_the_deck_records_whether_research_was_used():
    assert run().buyer.researched is True
    assert run(research=None).buyer.researched is False


def test_the_no_bid_warnings_do_not_mention_a_buyer_slide_it_does_not_have():
    weak = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.2)]}
    p = run(research=None, req=weak)
    assert "research unavailable (no research result)" in bid_warnings(p)
    assert not any("buyer slide" in w for w in bid_warnings(p))


def test_the_no_bid_recommendation_speaks_to_sales_not_to_code():
    weak = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.2)]}
    text = run(req=weak).recommendation
    assert "force_bid" not in text and "full proposal can still be generated" in text


# ---------- research incomplete ----------

def test_usable_research_with_missing_fields_raises_one_warning_listing_them():
    p = run(research={**DONE, "status": "partial", "estimated_revenue": None, "past_projects": []})
    assert "research incomplete: estimated_revenue, past_projects" in bid_warnings(p)
    assert sum(w.startswith("research incomplete") for w in bid_warnings(p)) == 1


def test_complete_research_raises_no_incomplete_warning():
    assert not any(w.startswith("research incomplete") for w in bid_warnings(run()))


def test_unusable_research_is_reported_as_unavailable_not_as_incomplete():
    w = bid_warnings(run(research=None))
    assert not any(x.startswith("research incomplete") for x in w)


def test_the_buyer_profile_has_no_footprint():
    assert not hasattr(run().buyer.profile, "footprint")


# ---------- expired tender ----------

@pytest.mark.parametrize("tender,expected", [
    ({**TENDER, "deadline": "2000-01-31"}, "tender deadline has passed (2000-01-31)"),
    ({**TENDER, "quality": {"is_expired": True}}, "tender deadline has passed"),
])
def test_an_expired_tender_raises_a_warning(tender, expected):
    assert expected in bid_warnings(run(tender=tender))


@pytest.mark.parametrize("deadline", ["2999-12-31", None, "next Friday", ""])
def test_a_future_missing_or_unreadable_deadline_raises_no_expiry_warning(deadline):
    w = bid_warnings(run(tender={**TENDER, "deadline": deadline}))
    assert not any("deadline has passed" in x for x in w)


def test_the_no_bid_deck_carries_the_expiry_warning_too():
    weak = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.2)]}
    p = run(tender={**TENDER, "deadline": "2000-01-31"}, req=weak)
    assert isinstance(p, NoBid) and "tender deadline has passed (2000-01-31)" in bid_warnings(p)


# ---------- phase2 ingest warnings ----------

def test_each_ingest_warning_from_detection_becomes_a_bid_warning():
    tender = {**TENDER, "quality": {"warnings": ["llm_unavailable", "possible_duplicate_of:t-9"]}}
    w = bid_warnings(run(tender=tender))
    assert "tender ingest warning: llm_unavailable" in w
    assert "tender ingest warning: possible_duplicate_of:t-9" in w


def test_a_tender_without_ingest_warnings_raises_none():
    assert not any(w.startswith("tender ingest warning") for w in bid_warnings(run()))


def test_the_no_bid_deck_carries_the_ingest_warnings_too():
    weak = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.2)]}
    p = run(tender={**TENDER, "quality": {"warnings": ["llm_unavailable"]}}, req=weak)
    assert isinstance(p, NoBid) and "tender ingest warning: llm_unavailable" in bid_warnings(p)
