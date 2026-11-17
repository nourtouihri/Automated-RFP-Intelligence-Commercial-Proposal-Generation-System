"""Prose that promises faster delivery than a duration or deadline the tender states."""

import copy

import pytest

from proposal.compose import bid_warnings, compose, speed_promises, tender_duration
from proposal.tests.test_compose import CVS, PRJ, RECORDS, REPLIES, REQ, RESEARCH, TENDER, fake_llm


@pytest.mark.parametrize("text,found", [
    ("Opt-outs must reach downstream systems within 24 hours.", "within 24 hours"),
    ("Changes propagate within one day.", "within one day"),
    ("The interim arrangement ends in eleven weeks.", "ends in eleven weeks"),
    ("Migration of 14 years of case history.", None),
    ("It moves 90,000 parcels a day.", None),
    ("Go-live no later than 30 June 2027.", "no later than 30 June 2027"),
    ("The submission deadline is firm.", "deadline"),
    ("We want a modern data platform.", None),
])
def test_the_duration_or_deadline_a_tender_states_is_found(text, found):
    assert tender_duration({"raw_text": text}) == found


DAY = {"raw_text": "Consent changes must reach downstream systems within 24 hours."}


@pytest.mark.parametrize("prose,word", [
    ("Enable same-day opt-out flow to all downstream tools.", "same-day"),
    ("Changes reach marketing immediately.", "immediately"),
    ("Instant consent sync.", "instant"),
    ("Real-time propagation of opt-outs.", "real-time"),
    ("Opt-outs reach systems in real time.", "real time"),
])
def test_a_speed_promise_under_a_stated_duration_is_flagged(prose, word):
    out = speed_promises([("summary.pillars[1].body", prose)], DAY)
    assert out == [f'speed promise "{word}" in summary.pillars[1].body; the tender states '
                   '"within 24 hours"']


def test_no_flag_when_the_tender_states_no_duration_or_deadline():
    assert speed_promises([("x", "Instant consent sync.")], {"raw_text": "A modern platform."}) == []


def test_no_flag_for_a_word_the_tender_itself_uses():
    tender = {"raw_text": "Real-time dashboards, refreshed within 5 minutes."}
    assert speed_promises([("x", "Real-time dashboards for the board.")], tender) == []


def test_no_flag_for_prose_that_keeps_to_the_stated_duration():
    assert speed_promises([("x", "Opt-outs propagate within one day.")], DAY) == []


def test_the_requirements_count_as_tender_text():
    tender = {"raw_text": "", "requirements": ["Consent propagation within 24 hours"]}
    assert speed_promises([("x", "Immediate consent sync.")], tender) != []


def test_a_speed_promise_in_a_deck_becomes_a_bid_warning():
    summary = copy.deepcopy(REPLIES["summary"])
    summary["pillars"][0]["body"] = "Same-day opt-out to every tool."
    tender = {**TENDER, "raw_text": "Opt-outs must reach every tool within 24 hours."}
    p = compose(tender, RESEARCH, REQ, CVS, PRJ, fake_llm({"summary": [summary]}), records=RECORDS)
    assert ('speed promise "same-day" in summary.pillars[0].body; the tender states '
            '"within 24 hours"') in bid_warnings(p)
