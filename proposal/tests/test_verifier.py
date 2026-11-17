"""The grounding verifier: field scoping, the verdict ruling, the quote rail,
and the warnings it produces (proposal/verifier.py, compose._from_verifier)."""

import json

import pytest

from proposal.compose import EvidenceOut, LetterOut, SummaryOut, Trace, bid_warnings, compose, run_step
from proposal.demo import ReplayExhausted, _replay_verifier
from proposal.llm_adapter import same_model_note
from proposal.verifier import INVALID_JSON_FIX, Verifier, _fields, _quote_found
from proposal.tests.test_compose import (CVS, PRJ, RECORDS, REQ, RESEARCH, TENDER,
                                         fake_llm, REPLIES)

MODEL = "judge-0"
ASSET = {"id": "PRJ-0003", "type": "project", "text": "Central data hub for the utility"}
EVIDENCE_PAYLOAD = {"REQUIREMENT": "ETL pipelines", "ASSET": ASSET}
LETTER_PAYLOAD = {"BRIEF": {}, "BUYER": "Sonede", "TENDER_TITLE": "t"}
SUMMARY_PAYLOAD = {"BRIEF": {"headline": "h"}, "ASSETS": [{"id": "PRJ-0003",
                  "type": "project", "text": "Central data hub"}]}


def judge_reply(pairs):
    """A judge reply: one {"field", "verdict", "quote", "reason"} per offered field."""
    return json.dumps({"verdicts": [{"field": f, "verdict": v, "quote": q, "reason": r}
                                    for f, v, q, r in pairs]})


def judge_script(script, seen=None):
    """A judge that answers each call from a script; `seen` collects requests."""
    replies = list(script)

    def judge(system, user):
        if seen is not None:
            seen.append(json.loads(user))
        return replies.pop(0)
    return judge


def judge_echo(quote, override=None):
    """A judge that reads its FIELDS and rules on each: supported by default."""
    def judge(system, user):
        fields = json.loads(user)["FIELDS"]
        rules = override or {}
        return judge_reply([(f["field"], *rules.get(f["field"],
                                                    ("supported", quote, "as stated")))
                            for f in fields])
    return judge


def judged(name, schema, payload, judge, *, allowed_ids=frozenset()):
    """One run_step with the fake writer and the given judge; (output, verdicts)."""
    trace = Trace()
    out = run_step(name, schema, payload, fake_llm(), trace, allowed_ids=allowed_ids,
                   records=RECORDS, verifier=Verifier(judge=judge, model=MODEL))
    return out, next(s for s in trace.steps if s["step"] == name)["verifier"]


def test_the_judge_sees_only_the_checked_fields_and_what_they_cite():
    seen = []
    good = judge_reply([("pillars[0].body", "supported", "Central data hub", "quoted"),
                        ("pillars[1].body", "partial", "", "says less"),
                        ("pillars[2].body", "unsupported", "", "not stated"),
                        ("why_us", "partial", "", "says less")])
    _, rows = judged("summary", SummaryOut, SUMMARY_PAYLOAD, judge_script([good], seen),
                     allowed_ids={"PRJ-0003", "CV-0002"})
    request = seen[0]
    assert request["STEP"] == "summary"
    fields = {f["field"]: f for f in request["FIELDS"]}
    assert set(fields) == {"pillars[0].body", "pillars[1].body", "pillars[2].body", "why_us"}
    assert fields["pillars[0].body"]["ids"] == ["PRJ-0003"]
    assert fields["pillars[1].body"]["ids"] == ["CV-0002"]
    assert fields["why_us"]["ids"] == []          # uncited: judged against INPUT
    sources = request["SOURCES"]
    assert sources["PRJ-0003"] == {"chunk": "Central data hub", "record": RECORDS["PRJ-0003"]}
    assert sources["CV-0002"] == {"record": RECORDS["CV-0002"]}  # no chunk view for this id
    assert sources["INPUT"] == SUMMARY_PAYLOAD
    assert [r["verdict"] for r in rows] == ["supported", "partial", "unsupported", "partial"]


def test_an_evidence_line_is_judged_against_only_its_own_asset():
    seen = []
    judged("evidence", EvidenceOut, EVIDENCE_PAYLOAD,
           judge_script([judge_reply([("line", "supported", "Central data hub", "quoted")])], seen),
           allowed_ids={"PRJ-0003"})
    request = seen[0]
    assert [f["field"] for f in request["FIELDS"]] == ["line"]
    assert request["FIELDS"][0]["ids"] == ["PRJ-0003"]
    assert set(request["SOURCES"]) == {"PRJ-0003"} and "INPUT" not in request["SOURCES"]


def test_field_scoping_across_steps_matches_the_claim_checks():
    dump = {s: json.loads(json.dumps(REPLIES[s])) for s in REPLIES}
    assert [f["field"] for f in _fields("brief", dump["brief"], {})] == \
        [f"key_messages[{i}]" for i in range(3)]
    assert [f["field"] for f in _fields("letter", dump["letter"], {})] == \
        ["paragraphs[0]", "closing"]
    assert [f["field"] for f in _fields("needs", dump["needs"], {})] == ["needs[0].body"]
    assert [f["field"] for f in _fields("approach", dump["approach"], {})] == \
        ["phases[0].body", "phases[1].body"]
    for step, payload in (("brief", {}), ("letter", {}), ("needs", {})):
        assert all(f["ids"] == [] for f in _fields(step, dump[step], payload))


def test_a_supported_claim_with_a_verbatim_quote_stands():
    out, rows = judged("evidence", EvidenceOut, EVIDENCE_PAYLOAD,
                       judge_echo("Central data hub"), allowed_ids={"PRJ-0003"})
    assert out.line == "Utility data hub for water data"  # the writer's line, untouched
    assert rows == [{"field": "line", "verdict": "supported",
                     "reason": "as stated", "quote": "Central data hub", "judge": MODEL}]


def test_a_supported_claim_without_a_findable_quote_is_downgraded_to_partial():
    _, rows = judged("evidence", EvidenceOut, EVIDENCE_PAYLOAD,
                     judge_echo("a span the source never said"), allowed_ids={"PRJ-0003"})
    assert rows[0]["verdict"] == "partial"
    assert "code could not find the quote" in rows[0]["reason"]
    assert rows[0]["quote"] == "a span the source never said"


def test_the_quote_rail_tolerates_dashes_spacing_and_json_separators():
    assert _quote_found("Central - hub", ["Central \u2013 hub, one stop."])
    assert _quote_found("Central hub.", ["Central\n hub."])
    assert _quote_found('summary": "Central data hub", "client_sector": "utilities"',
                        [json.dumps(RECORDS["PRJ-0003"], ensure_ascii=False)])
    assert not _quote_found("Central hub works", ["Central hub, one stop."])
    assert not _quote_found("   ", ["anything"])


def test_partial_and_unsupported_reach_bid_warnings_supported_is_silent():
    def judge(system, user):
        fields = json.loads(user)["FIELDS"]
        return judge_reply([(f["field"], "partial", None, "the source says less")
                            if i % 2 else
                            (f["field"], "unsupported", None, "no source states it")
                            for i, f in enumerate(fields)])

    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS, trace=trace,
                verifier=Verifier(judge=judge, model=MODEL))
    letter_rows = next(s["verifier"] for s in trace.steps
                       if s["step"] == "letter" and isinstance(s.get("verifier"), list))
    assert [r["verdict"] for r in letter_rows] == ["unsupported", "partial"]
    warnings = bid_warnings(p, trace)
    assert ("verifier: unsupported claim in letter.paragraphs[0]: no source states it"
            in warnings)
    assert ("verifier: partial support in letter.closing: the source says less" in warnings)


def test_syntax_failures_are_retried_with_the_exact_feedback_then_verdicts():
    seen = []
    judge = judge_script(["not json",
                          judge_reply([("paragraphs[0]", "supported", "Sonede", "quoted"),
                                       ("closing", "supported", "Sonede", "quoted")])], seen)
    _, rows = judged("letter", LetterOut, LETTER_PAYLOAD, judge)
    assert [r["verdict"] for r in rows] == ["supported", "supported"]
    first_user, second_user = seen
    assert "FIX_PREVIOUS_REPLY" not in first_user
    assert second_user["FIX_PREVIOUS_REPLY"] == [INVALID_JSON_FIX]


def test_a_field_or_count_mismatch_is_told_the_exact_order():
    seen = []
    judge = judge_script([judge_reply([("closing", "partial", None, "one item only")]),
                          judge_reply([("paragraphs[0]", "partial", None, "now in order"),
                                       ("closing", "supported", "Sonede", "quoted")])], seen)
    _, rows = judged("letter", LetterOut, LETTER_PAYLOAD, judge)
    assert [r["verdict"] for r in rows] == ["partial", "supported"]
    assert ("return exactly one verdict per FIELDS item, in this order: "
            "paragraphs[0], closing") in seen[1]["FIX_PREVIOUS_REPLY"][0]


def test_a_judge_that_keeps_failing_is_recorded_unavailable_and_warns():
    def broken(system, user):
        return "{{}}"  # braces, but not one JSON object

    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS, trace=trace,
                verifier=Verifier(judge=broken, model=MODEL))
    evidence = next(s for s in trace.steps if s["step"] == "evidence")
    assert evidence["verifier"] == {"error": "after 3 attempts: not valid JSON"}
    assert ("grounding check unavailable: evidence: after 3 attempts: not valid JSON"
            in bid_warnings(p, trace))


def test_a_transport_failure_says_judge_call_failed():
    def broken(system, user):
        raise RuntimeError("HTTP 429: slow down")

    _, rows = judged("evidence", EvidenceOut, EVIDENCE_PAYLOAD, broken,
                     allowed_ids={"PRJ-0003"})
    assert rows["error"].startswith("judge call failed: HTTP 429")


def test_the_pipeline_judges_every_step_and_never_the_no_bid():
    calls = []

    def judge(system, user):
        calls.append(json.loads(user)["STEP"])
        fields = json.loads(user)["FIELDS"]
        return judge_reply([(f["field"], "partial", None, "the source says less")
                            for f in fields])

    trace = Trace()
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS, trace=trace,
            verifier=Verifier(judge=judge, model=MODEL))
    # five writer steps plus the one model-written evidence row, each judged once,
    # in the order compose runs them ("Arabic training" is a code row: no evidence step)
    assert calls == ["brief", "letter", "summary", "needs", "evidence", "approach"]
    assert all(isinstance(s.get("verifier"), list) for s in trace.steps)
    count = sum(len(s["verifier"]) for s in trace.steps)
    warnings = bid_warnings(compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(),
                                    records=RECORDS), trace)
    partial = [w for w in warnings if w.startswith("verifier: partial support in ")]
    assert len(partial) == count == 13
    assert "verifier: partial support in brief.key_messages[0]: the source says less" in partial

    # a no-bid deck never reaches the model, so the judge is never called
    before = list(calls)
    weak = {"ETL pipelines": [dict(REQ["ETL pipelines"][1], similarity=0.31)],
            "Arabic training": [dict(REQ["ETL pipelines"][1], similarity=0.2)]}
    no_bid_trace = Trace()
    no_bid = compose(TENDER, RESEARCH, weak, [], [], fake_llm(), trace=no_bid_trace,
                     verifier=Verifier(judge=judge, model=MODEL))
    assert calls == before and no_bid_trace.steps == []


def test_the_replay_judge_is_served_from_the_recording_in_order():
    verifier, note = _replay_verifier({"source": {"model": "w", "verifier_model": "j"},
                                       "verifier": [{"step": "brief", "reply": "one"},
                                                    {"step": "evidence", "reply": "two"}]})
    assert verifier.model == "j" and note is None
    assert verifier._judge("s", json.dumps({"STEP": "brief"})) == "one"
    assert verifier._judge("s", json.dumps({"STEP": "evidence"})) == "two"
    with pytest.raises(ReplayExhausted, match="no more verifier replies for step 'brief'"):
        verifier._judge("s", json.dumps({"STEP": "brief"}))
    assert _replay_verifier({"source": {}, "replies": []}) == (None, None)


def test_the_replay_judge_warns_when_it_used_the_writers_model():
    verifier, note = _replay_verifier({"source": {"model": "w", "verifier_model": "w"},
                                       "verifier": [{"step": "brief", "reply": "{}"}]})
    assert verifier is not None and note
    assert "writer's model" in note and "blind spots" in note


def test_same_model_note_only_fires_for_the_writers_model(monkeypatch):
    monkeypatch.delenv("PROPOSAL_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "writer")
    assert "blind spots" in same_model_note("WRITER")
    assert same_model_note("another model") is None
