import copy
import json

import pytest

from proposal.compose import (TASKS, StepError, Trace, bid_warnings, compose, evidence_hit,
                              is_delivered, retrieved_ids)

TENDER = {"id": "tender-001", "title": "Data platform", "issuer": "Sonede",
          "requirements": ["ETL pipelines", "Arabic training"], "raw_text": "..."}
RESEARCH = {"sector": "Water utility", "key_partners": ["Ministry of Agriculture"]}
GAPS = "research incomplete: estimated_revenue, past_projects"  # what RESEARCH leaves out


def hit(chunk_id, record_id, doc_type, similarity, content="", **meta):
    """A row shaped like shared.schemas.QueryResult, metadata as rag ingests it."""
    return {"id": chunk_id, "content": content, "doc_type": doc_type, "source_file": "x.json",
            "metadata": {"record_id": record_id, **meta}, "similarity": similarity,
            "ranking_score": similarity}


IDEA = hit("c9", "olivesoft-027", "project", 0.6, name="GDPR data catalogue",
           project_kind="pfe_internship_project", evidence_status="proposed")
REQ = {"ETL pipelines": [IDEA, hit("c1", "PRJ-0003", "project", 0.871, "Utility data hub",
                                   client_sector="utilities")],
       "Arabic training": []}
CVS = [hit("c2", "CV-0002", "cv", 0.9, person="Employee_002", role="Data engineer",
           skills=["Airflow", "dbt"])]
PRJ = [IDEA, hit("c3", "PRJ-0003", "project", 0.87, client_sector="utilities")]
RECORDS = {
    "CV-0002": {"cv_id": "CV-0002", "name": "Employee_002", "role": "Data engineer",
                "years_experience": 7, "skills": ["Airflow", "dbt"]},
    "PRJ-0003": {"project_id": "PRJ-0003", "summary": "Central data hub",
                 "client_sector": "utilities", "outcome": "Handed over to internal IT."},
    "olivesoft-027": {"id": "olivesoft-027", "name": "GDPR data catalogue",
                      "description": "PFE idea", "outcome": "proposed",
                      "relationship": "pfe_internship_project"},
}

REPLIES = {
    "brief": {"headline": "A single data platform for Sonede", "subtitle": "Integration without silos.",
              "key_messages": ["a", "b", "c"], "tone": "confident"},
    "letter": {"salutation": "Dear committee,", "paragraphs": ["Thank you."], "closing": "Best."},
    "summary": {"title": "Reliable data", "why_us": "Why OliveSoft: references.",
                "pillars": [{"title": "Integrated", "body": "x", "evidence": ["PRJ-0003"]},
                            {"title": "Skilled", "body": "x", "evidence": ["CV-0002"]},
                            {"title": "Safe", "body": "x", "evidence": []}]},
    "needs": {"needs": [{"title": "Siloed data", "body": "Sources are not linked."}]},
    "evidence": {"line": "Utility data hub for water data"},
    "approach": {"phases": [{"name": "Discover", "weeks": 2, "body": "Audit."},
                            {"name": "Build", "weeks": 6, "body": "Build."}]},
}


def fake_llm(overrides=None, calls=None):
    def llm(system, user):
        step = next(k for k in REPLIES if system.endswith(TASKS[k]))
        if calls is not None:
            calls.append((step, json.loads(user)))
        queue = (overrides or {}).get(step)
        if queue:
            return json.dumps(queue.pop(0))
        return json.dumps(REPLIES[step])
    return llm


def test_pipeline_builds_proposal_with_facts_from_code():
    calls, trace = [], Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(calls=calls), records=RECORDS,
                trace=trace)
    assert [c[0] for c in calls] == ["brief", "letter", "summary", "needs", "evidence", "approach"]
    # the PFE idea ranked first is skipped as evidence; the delivered project is used
    assert p.requirements[0].evidence_id == "PRJ-0003" and p.requirements[0].score == 0.87
    assert p.requirements[1].evidence_id is None
    assert p.buyer.profile.sector == "Water utility" and p.buyer.profile.estimated_revenue == "Size not stated in the tender"
    assert (p.team[0].name, p.team[0].years) == ("Employee_002", 7)
    # an outcome without an explicit status is unverified; it still ranks above PFE ideas
    assert [(r.project_id, r.delivered) for r in p.references] == [("PRJ-0003", None),
                                                                   ("olivesoft-027", False)]
    assert retrieved_ids(p) == {"PRJ-0003", "CV-0002", "olivesoft-027"}
    assert all(s["ok"] for s in trace.steps)


def test_each_step_sees_only_its_own_inputs():
    calls = []
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(calls=calls), records=RECORDS)
    seen = dict(calls)
    assert set(seen["evidence"]) == {"REQUIREMENT", "ASSET"}
    assert "ASSETS" not in seen["needs"] and "RESEARCH" not in seen["summary"]


def test_invented_citation_is_retried_then_accepted():
    bad = json.loads(json.dumps(REPLIES["summary"]))
    bad["pillars"][2]["evidence"] = ["PRJ-9999"]
    trace = Trace()
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"summary": [bad]}), trace=trace)
    assert next(s for s in trace.steps if s["step"] == "summary")["attempts"] == 2


def test_step_that_keeps_failing_raises_with_its_name():
    with pytest.raises(StepError, match="'needs'"):
        compose(TENDER, RESEARCH, REQ, CVS, PRJ,
                fake_llm({"needs": [{"needs": []}, {"oops": 1}, {"oops": 1}]}))


def test_is_delivered_rules():
    assert not is_delivered({"outcome": "proposed"})
    assert not is_delivered({"outcome": None})
    assert is_delivered({"outcome": "Delivered on schedule"}) is None
    assert is_delivered({"status": "delivered", "outcome": "Delivered on schedule"})
    # chunk metadata alone (no source record): a project hit has no outcome
    assert not is_delivered({"project_kind": "pfe_internship_project", "evidence_status": "proposed"})


def test_metadata_only_hits_still_compose():
    """Without the source records nothing is guessed: no years, and no project
    is claimed delivered (project hit metadata carries no outcome)."""
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm())
    assert p.team[0].name == "Employee_002" and p.team[0].years is None
    assert [r.title for r in p.references] == ["PRJ-0003", "GDPR data catalogue"]
    assert not any(r.delivered for r in p.references)


def test_evidence_hit_skips_ideas():
    assert evidence_hit([IDEA]) is None
    assert evidence_hit(REQ["ETL pipelines"])["id"] == "c1"


def test_weak_hit_is_written_by_code_not_the_model():
    calls = []
    weak = {"Allergen evidence": [hit("c4", "PRJ-0003", "project", 0.17, "Utility data hub")]}
    p = compose(TENDER, RESEARCH, weak, CVS, PRJ, fake_llm(calls=calls), records=RECORDS,
                force_bid=True)
    assert "evidence" not in [c[0] for c in calls] and "brief" in [c[0] for c in calls]
    assert p.requirements[0].evidence == "Weak match only, flagged for review"
    assert p.requirements[0].fit == "Gap"


def test_bid_warnings_flag_an_out_of_scope_tender():
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS)
    assert bid_warnings(p) == [GAPS]
    weak = {"Allergen evidence": [hit("c4", "PRJ-0003", "project", 0.17)]}
    uncited = json.loads(json.dumps(REPLIES["summary"]))
    for pillar in uncited["pillars"]:
        pillar["evidence"] = []
    p = compose(TENDER, RESEARCH, weak, [hit("c2", "CV-0002", "cv", 0.3)], [IDEA],
                fake_llm({"summary": [uncited]}), records=RECORDS, force_bid=True)
    assert bid_warnings(p) == [GAPS, "no requirement has strong evidence",
                               "no delivered reference project",
                               "every matched consultant is a weak match"]


def test_trace_records_why_each_failed_attempt_failed():
    bad = json.loads(json.dumps(REPLIES["summary"]))
    bad["pillars"][0]["evidence"] = ["PRJ-9999"]
    trace = Trace()
    compose(TENDER, RESEARCH, REQ, CVS, PRJ,
            fake_llm({"summary": [bad], "needs": [{"oops": 1}]}), records=RECORDS, trace=trace)
    steps = {s["step"]: s for s in trace.steps}
    assert [f["kind"] for f in steps["summary"]["failures"]] == ["citation"]
    assert [f["kind"] for f in steps["needs"]["failures"]] == ["parse"]
    assert steps["brief"]["failures"] == []


def overlong(step, **fields):
    reply = json.loads(json.dumps(REPLIES[step]))
    reply.update(fields)
    return reply


def test_retry_feeds_back_the_exact_overage():
    calls = []
    compose(TENDER, RESEARCH, REQ, CVS, PRJ,
            fake_llm({"brief": [overlong("brief", subtitle="x" * 92)]}, calls=calls),
            records=RECORDS)
    first, retry = [payload for step, payload in calls if step == "brief"]
    assert "FIX_PREVIOUS_REPLY" not in first
    assert retry["FIX_PREVIOUS_REPLY"] == [
        "subtitle has 92 characters, limit 80: remove at least 12 (aim for 68)"]


def test_overlong_text_is_cut_at_a_sentence_after_three_misses():
    why = "Local references in water. " + "Long second sentence " * 9 + "here."
    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ,
                fake_llm({"summary": [overlong("summary", why_us=why)] * 3}),
                records=RECORDS, trace=trace)
    assert p.summary.why_us == "Local references in water."
    step = next(s for s in trace.steps if s["step"] == "summary")
    assert step["ok"] and step["attempts"] == 3
    assert step["trimmed"] == [{"field": "why_us", "from": len(why), "to": 26, "how": "sentence"}]
    assert "1 text field cut by code to fit: summary.why_us" in bid_warnings(p, trace)


def test_one_long_sentence_is_cut_at_a_word():
    subtitle = "Integration of every regional source into one governed platform for the water utility"
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ,
                fake_llm({"brief": [overlong("brief", subtitle=subtitle)] * 3}), records=RECORDS)
    assert len(p.meta.subtitle) <= 80 and subtitle.startswith(p.meta.subtitle)
    assert subtitle[len(p.meta.subtitle)] == " "


def test_citation_failures_are_never_trimmed():
    bad = overlong("summary")
    bad["pillars"][0]["evidence"] = ["PRJ-9999"]
    with pytest.raises(StepError, match="'summary'"):
        compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"summary": [bad] * 3}), records=RECORDS)


def test_text_without_spaces_is_cut_at_the_limit():
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ,
                fake_llm({"brief": [overlong("brief", subtitle="x" * 92)] * 3}), records=RECORDS)
    assert p.meta.subtitle == "x" * 80


def test_a_list_over_its_limit_is_cut_to_the_first_items_and_flagged():
    trace = Trace()
    letter = {**REPLIES["letter"], "paragraphs": ["First.", "Second.", "Third."]}
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"letter": [letter] * 3}),
                records=RECORDS, trace=trace)
    assert p.letter.paragraphs == ["First.", "Second."]
    step = next(s for s in trace.steps if s["step"] == "letter")
    assert step["ok"] and step["attempts"] == 3
    assert step["trimmed"] == [{"field": "paragraphs", "from": 3, "to": 2, "how": "list"}]
    assert ("1 list shortened by code (first items kept): letter.paragraphs 3 -> 2"
            in bid_warnings(p, trace))


def test_retry_names_the_list_that_ran_over():
    calls = []
    letter = {**REPLIES["letter"], "paragraphs": ["a.", "b.", "c."]}
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"letter": [letter]}, calls=calls),
            records=RECORDS)
    retry = [payload for step, payload in calls if step == "letter"][1]
    assert retry["FIX_PREVIOUS_REPLY"] == ["paragraphs has 3 items, limit 2: remove at least 1"]


def test_strings_of_a_dropped_list_item_are_not_cut_twice():
    letter = {**REPLIES["letter"], "paragraphs": ["ok.", "ok too.", "x" * 300]}
    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"letter": [letter] * 3}),
                records=RECORDS, trace=trace)
    assert p.letter.paragraphs == ["ok.", "ok too."]
    step = next(s for s in trace.steps if s["step"] == "letter")
    assert [t["how"] for t in step["trimmed"]] == ["list"]


@pytest.mark.parametrize("raw", ["{not json}", "Sorry, no braces in this reply"])
def test_invalid_json_is_retried_with_a_json_only_instruction(raw):
    seen, first = [], [raw]
    base = fake_llm()

    def llm(system, user):
        if system.endswith(TASKS["brief"]):
            seen.append(json.loads(user))
            if first:
                return first.pop()
        return base(system, user)
    trace = Trace()
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, llm, records=RECORDS, trace=trace)
    assert "FIX_PREVIOUS_REPLY" not in seen[0]
    assert seen[1]["FIX_PREVIOUS_REPLY"] == [
        "your last reply was not valid JSON; return one JSON object only"]
    assert next(s for s in trace.steps if s["step"] == "brief")["attempts"] == 2


def test_valid_json_with_the_wrong_shape_gets_no_json_instruction():
    calls = []
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"needs": [{"oops": 1}]}, calls=calls),
            records=RECORDS)
    retry = [payload for step, payload in calls if step == "needs"][1]
    assert "FIX_PREVIOUS_REPLY" not in retry


def test_banned_wording_adds_one_warning_per_hit_naming_the_field():
    brief = {**REPLIES["brief"], "headline": "Proven platform for Sonede"}
    summary = json.loads(json.dumps(REPLIES["summary"]))
    summary["why_us"] = "Seamless, real‑time delivery, guaranteed."
    needs = {"needs": [{"title": "Uptime", "body": "Zero service disruption."}]}
    approach = {"phases": [{"name": "Discover", "weeks": 2, "body": "Audit."},
                           {"name": "Build", "weeks": 6,
                            "body": "A leading team: best-in-class, world-class, cutting-edge, "
                                    "unmatched."}]}
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ,
                fake_llm({"brief": [brief], "summary": [summary], "needs": [needs],
                          "approach": [approach]}), records=RECORDS)
    assert [w for w in bid_warnings(p) if w.startswith("banned")] == [
        'banned wording "proven" in meta.headline',
        'banned wording "seamless" in summary.why_us',
        'banned wording "real-time" in summary.why_us',
        'banned wording "guarantee" in summary.why_us',
        'banned wording "zero disruption" in buyer.needs[0].body',
        'banned wording "best-in-class" in approach.phases[1].body',
        'banned wording "world-class" in approach.phases[1].body',
        'banned wording "cutting-edge" in approach.phases[1].body',
        'banned wording "unmatched" in approach.phases[1].body',
        'banned wording "leading" in approach.phases[1].body',
    ]


def test_banned_wording_matches_whole_words_only():
    brief = {**REPLIES["brief"], "headline": "Leadership, unproven ideas, misleading"}
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"brief": [brief]}), records=RECORDS)
    assert bid_warnings(p) == [GAPS]


def test_a_word_repeated_in_one_field_is_one_warning():
    brief = {**REPLIES["brief"], "headline": "Proven and proven again"}
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"brief": [brief]}), records=RECORDS)
    assert bid_warnings(p) == [GAPS, 'banned wording "proven" in meta.headline']


def test_claims_the_inputs_do_not_contain_become_bid_warnings():
    brief = {**REPLIES["brief"], "key_messages": ["Delivered for 40% less since 2019.", "b", "c"]}
    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"brief": [brief]}), records=RECORDS,
                trace=trace, claim_check=True)
    warnings = bid_warnings(p, trace)
    assert 'unsupported status "delivered" in brief.key_messages[0]' in warnings
    assert 'unsupported percentage "40%" in brief.key_messages[0]' in warnings
    assert 'unsupported year "2019" in brief.key_messages[0]' in warnings
    step = next(s for s in trace.steps if s["step"] == "brief")
    assert step["unsupported"][0]["field"] == "key_messages[0]"


def test_the_claim_check_is_off_unless_asked():
    brief = {**REPLIES["brief"], "key_messages": ["Delivered for 40% less since 2019.", "b", "c"]}
    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"brief": [brief]}), records=RECORDS,
                trace=trace)
    assert not [w for w in bid_warnings(p, trace) if w.startswith("unsupported")]


def test_titles_and_labels_are_outside_the_claim_check():
    brief = {**REPLIES["brief"], "headline": "Delivered for 40% less", "subtitle": "Since 2019 at Globex Corp"}
    needs = {"needs": [{"title": "Cut 40% in 2019", "body": "Sources are not linked."}]}
    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"brief": [brief], "needs": [needs]}),
                records=RECORDS, trace=trace, claim_check=True)
    assert not [w for w in bid_warnings(p, trace) if w.startswith("unsupported")]


def test_clean_prose_gets_no_unsupported_warning():
    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS, trace=trace,
                claim_check=True)
    assert not [w for w in bid_warnings(p, trace) if w.startswith("unsupported")]
    assert all("unsupported" not in s for s in trace.steps)


def test_a_claim_in_the_source_record_but_not_the_chunk_is_supported():
    with_fact = {**RECORDS, "PRJ-0003": {**RECORDS["PRJ-0003"], "outcome": "56% fewer notices."}}
    flagged = []
    for records in (RECORDS, with_fact):
        trace = Trace()
        llm = fake_llm({"evidence": [{"line": "56% fewer notices"}]})
        p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, llm, records=records, trace=trace,
                    claim_check=True)
        flagged.append([w for w in bid_warnings(p, trace) if "56%" in w])
    assert flagged == [['unsupported percentage "56%" in evidence.line'], []]


def test_a_cited_id_is_not_read_as_an_invented_name_or_number():
    trace = Trace()
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm(), records=RECORDS, trace=trace,
            claim_check=True)
    summary = next(s for s in trace.steps if s["step"] == "summary")
    assert not [u for u in summary.get("unsupported", []) if "evidence" in u["field"]]


def test_trimming_a_list_that_hides_an_overlong_item_still_ends_in_a_valid_reply():
    # pydantic reports only "too many paragraphs"; the long first one is never mentioned
    # until the list is cut, so the cut has to be checked again.
    letter = {**REPLIES["letter"], "paragraphs": ["word " * 52, "short.", "third."]}
    trace = Trace()
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"letter": [letter] * 3}), records=RECORDS,
                trace=trace)
    assert len(p.letter.paragraphs) == 2 and all(len(x) <= 220 for x in p.letter.paragraphs)
    step = next(s for s in trace.steps if s["step"] == "letter")
    assert sorted(t["how"] for t in step["trimmed"]) == ["list", "word"]


def test_a_reply_that_cannot_be_trimmed_into_shape_is_a_step_error_never_a_raw_validation_error():
    import random

    from proposal.compose import ApproachOut, BriefOut, LetterOut, NeedsOut, SummaryOut, run_step
    schemas = {"brief": BriefOut, "letter": LetterOut, "summary": SummaryOut, "needs": NeedsOut,
               "approach": ApproachOut}
    rng = random.Random(7)

    def mangle(node):
        if isinstance(node, str):
            return node + " word" * rng.choice([0, 0, 5, 60]) if rng.random() < 0.5 else node
        if isinstance(node, list):
            items = [mangle(x) for x in node]
            return items * rng.choice([1, 1, 2, 3]) if rng.random() < 0.3 else items
        if isinstance(node, dict):
            out = {k: mangle(v) for k, v in node.items()}
            if rng.random() < 0.05:
                out["extra"] = 1
            return out
        return node
    for _ in range(400):
        step = rng.choice(sorted(schemas))
        raw = json.dumps(mangle(copy.deepcopy(REPLIES[step])))
        try:
            run_step(step, schemas[step], {"ASSETS": []}, lambda s, u: raw, Trace())
        except StepError:
            pass


def test_the_last_resort_cut_uses_the_least_overlong_reply_not_just_the_last_attempt():
    first = {**REPLIES["brief"], "subtitle": "word " * 18}            # 90 characters, 10 over
    second = {**REPLIES["brief"], "subtitle": "second " * 12}          # 84 characters, 4 over
    garbled = '{"headline": "x", "subti'                                # a truncated third reply
    queue = [json.dumps(first), json.dumps(second), garbled]
    base, trace = fake_llm(), Trace()

    def llm(system, user):
        return queue.pop(0) if system.endswith(TASKS["brief"]) and queue else base(system, user)
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, llm, records=RECORDS, trace=trace)
    step = next(s for s in trace.steps if s["step"] == "brief")
    assert step["ok"] and step["attempts"] == 3 and step["trim_attempt"] == 2
    assert p.meta.subtitle.startswith("second second") and len(p.meta.subtitle) <= 80
    assert [t["how"] for t in step["trimmed"]] == ["word"]


def test_an_earlier_reply_with_a_smaller_overage_wins_over_a_later_one():
    first = {**REPLIES["brief"], "subtitle": "first " * 14}            # 84 characters, 4 over
    second = {**REPLIES["brief"], "subtitle": "second " * 20}          # 140 characters, 60 over
    queue = [json.dumps(first), json.dumps(second), json.dumps(second)]
    base, trace = fake_llm(), Trace()

    def llm(system, user):
        return queue.pop(0) if system.endswith(TASKS["brief"]) and queue else base(system, user)
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, llm, records=RECORDS, trace=trace)
    assert next(s for s in trace.steps if s["step"] == "brief")["trim_attempt"] == 1
    assert p.meta.subtitle.startswith("first first")


def test_a_reply_that_cites_an_invented_id_is_never_the_one_that_gets_cut():
    ok = copy.deepcopy(REPLIES["summary"])
    ok["why_us"] = "word " * 42                                        # 210 characters, 20 over
    invented = copy.deepcopy(REPLIES["summary"])
    invented["why_us"] = "x " * 96                                     # 192 characters, 2 over
    invented["pillars"][0]["evidence"] = ["CV-9999"]
    queue = [json.dumps(ok), json.dumps(invented), "not json"]
    base, trace = fake_llm(), Trace()

    def llm(system, user):
        return queue.pop(0) if system.endswith(TASKS["summary"]) and queue else base(system, user)
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, llm, records=RECORDS, trace=trace)
    assert next(s for s in trace.steps if s["step"] == "summary")["trim_attempt"] == 1
    assert "CV-9999" not in [e for pl in p.summary.pillars for e in pl.evidence]


def test_a_reply_that_is_too_long_and_wrong_in_another_way_is_not_a_candidate():
    bad = {**REPLIES["brief"], "subtitle": "x" * 90, "extra": 1}
    with pytest.raises(StepError, match="'brief'"):
        compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"brief": [bad] * 3}), records=RECORDS)
