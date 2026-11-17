"""General tests: does compose() hold up beyond the fixtures it was built on?

B1 runs seeded random inputs (hypothesis is not installed): zero, one and 25
requirements, unicode and very long titles, missing fields, empty or weak
retrieval, duplicate ids, edge similarities. Each must end as a valid deck that
renders and passes the validator, or as a StepError. B2 plays adversarial
models and checks that each misbehaviour is caught. Some of these tests are
expected to fail: they report what the generator does not handle yet.
"""

from __future__ import annotations

import json
import random

import pytest

from proposal import render
from proposal.compose import TASKS, InputError, StepError, Trace, bid_warnings, compose, record_id
from proposal.schemas import NoBid
from proposal.tests.test_compose import CVS, PRJ, RECORDS, REQ, RESEARCH, TENDER
from proposal.validate import validate

SEEDS = range(6)
WORDS = "secure scalable integration governed audited platform dashboards pipelines migration".split()


def fill(n: int) -> str:
    out, i = "", 0
    while len(out) + len(WORDS[i % len(WORDS)]) + 1 <= n:
        out = (out + " " + WORDS[i % len(WORDS)]).strip()
        i += 1
    return out.capitalize()


def reply(step: str, payload: dict, ratio: float = 1.0) -> dict:
    """A well-behaved model: valid JSON at `ratio` of every limit, citing only its inputs."""
    n = lambda limit: fill(int(limit * ratio))  # noqa: E731
    if step == "brief":
        return {"headline": n(60), "subtitle": n(80), "key_messages": [n(80)] * 3, "tone": n(80)}
    if step == "letter":
        return {"salutation": "Dear committee,", "paragraphs": [n(220), n(220)], "closing": "Best."}
    if step == "summary":
        ids = [a["id"] for a in payload["ASSETS"]]
        return {"title": n(53), "why_us": n(190),
                "pillars": [{"title": n(28), "body": n(110), "evidence": ids[i:i + 1]}
                            for i in range(3)]}
    if step == "needs":
        return {"needs": [{"title": n(40), "body": n(120)}] * 3}
    if step == "evidence":
        return {"line": n(55)}
    return {"phases": [{"name": n(20), "weeks": w, "body": n(100)} for w in (1, 5, 4, 2)]}


def stand_in(ratio: float = 1.0, mutate=None, calls: list | None = None):
    def llm(system: str, user: str) -> str:
        step = next(k for k in TASKS if system.endswith(TASKS[k]))
        payload = json.loads(user)
        if calls is not None:
            calls.append(step)
        out = reply(step, payload, ratio)
        return json.dumps(mutate(step, out) or out if mutate else out)
    return llm


# ---------- B1: seeded random inputs ----------

UNICODE_TITLES = ["Plateforme d’analyse — données & IA", "منصة تحليل البيانات للمستشفيات",
                  "Analytics 📊 for ünïcödé Straße", "Université de Tunis — Phase 2 (2026–2028)"]
LONG_NAMES = ["x" * 400, " ".join(["Very long public tender title"] * 14)]


def make_hits(rng, doc_type, n, sim, start=0):
    prefix = "CV" if doc_type == "cv" else "PRJ"
    return [{"id": f"chunk-{prefix}-{start + i}", "content": f"{prefix} {fill(rng.randint(20, 300))}",
             "doc_type": doc_type, "source_file": "x.json",
             "metadata": {"record_id": f"{prefix}-{start + i:04d}"},
             "similarity": sim(), "ranking_score": 0.5} for i in range(n)]


def make_case(scenario: str, seed: int) -> dict:
    rng = random.Random(f"{scenario}-{seed}")
    sim = lambda: rng.uniform(0.0, 1.0)  # noqa: E731
    n_req = {"zero_requirements": 0, "one_requirement": 1, "twenty_five_requirements": 25}.get(
        scenario, rng.randint(2, 7))
    reqs = [f"Requirement {i}: {fill(rng.randint(10, 120))}" for i in range(n_req)]
    title, issuer = "Data platform", "Sonede"
    if scenario == "unicode_titles":
        title, issuer = rng.choice(UNICODE_TITLES), rng.choice(UNICODE_TITLES)
    if scenario == "very_long_names":
        title, issuer = rng.choice(LONG_NAMES), rng.choice(LONG_NAMES)[:200]
    tender = {"id": f"t-{seed}", "title": title, "issuer": issuer,
              "raw_text": fill(rng.randint(0, 5000)), "deadline": "2026-12-31",
              "source": "manual", "requirements": reqs}
    if scenario == "weak_hits":
        sim = lambda: rng.uniform(0.0, 0.39)  # noqa: E731
    if scenario == "edge_similarities":
        sim = lambda: rng.choice([-0.2, 0.0, 0.4, 0.55, 1.0, 1.0000001])  # noqa: E731
    cvs, prj = make_hits(rng, "cv", 3, sim), make_hits(rng, "project", 5, sim)
    matches = {r: make_hits(rng, "project", rng.randint(1, 5), sim, start=10) for r in reqs}
    if scenario == "duplicate_ids":
        # a strong project, so the result is a full proposal whose team can be inspected
        cvs, prj = [cvs[0]] * 3, [{**prj[0], "similarity": 0.8}] * 5
        matches = {r: [prj[0]] * 3 for r in reqs}
    if scenario == "missing_optional_fields":
        for key in rng.sample(["raw_text", "id", "deadline", "source"], rng.randint(1, 4)):
            tender.pop(key)
    if scenario == "missing_title_or_issuer":
        tender.pop(rng.choice(["title", "issuer"]))
    if scenario == "no_cv_matches":
        cvs = []
    if scenario == "no_project_matches":
        prj = []
    if scenario == "no_hits_for_any_requirement":
        matches = {r: [] for r in reqs}
    research = rng.choice([None, {}, {"sector": "Public sector", "key_partners": ["A", "B"]}])
    records = {}
    for h in [*cvs, *prj, *(h for hs in matches.values() for h in hs)]:
        rid = record_id(h)
        records[rid] = ({"cv_id": rid, "name": f"Employee_{rid}", "role": "Engineer",
                         "years_experience": rng.randint(0, 30), "skills": ["a", "b"]}
                        if rid.startswith("CV") else
                        {"project_id": rid, "summary": fill(60), "client_sector": "x",
                         "outcome": rng.choice([None, "proposed", "Handed over."])})
    given = {record_id(h) for h in [*cvs, *prj, *(h for hs in matches.values() for h in hs)]}
    return {"kwargs": dict(tender=tender, research=research, requirement_matches=matches,
                           cv_matches=cvs, project_matches=prj, records=records), "given": given}


SCENARIOS = ["zero_requirements", "one_requirement", "twenty_five_requirements",
             "unicode_titles", "very_long_names", "missing_optional_fields", "missing_title_or_issuer",
             "no_cv_matches", "no_project_matches", "no_hits_for_any_requirement", "weak_hits",
             "edge_similarities", "duplicate_ids"]


@pytest.fixture(scope="module", autouse=True)
def website_theme():
    render.apply_theme("website")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_random_inputs_end_in_a_valid_deck_or_a_clear_error(scenario, tmp_path):
    bad = {}
    for seed in SEEDS:
        case = make_case(scenario, seed)
        calls = []
        try:
            deck = compose(**case["kwargs"], llm=stand_in(calls=calls))
        except (StepError, InputError):
            continue
        except Exception as e:  # noqa: BLE001
            bad[seed] = f"crash after {len(calls)} LLM calls: {type(e).__name__}: {str(e)[:110]!r}"
            continue
        path = tmp_path / f"{seed}.pptx"
        if isinstance(deck, NoBid):
            render.render_no_bid(deck, str(path))
            issues = validate(str(path))
        else:
            render.render(deck, str(path))
            issues = validate(str(path), deck, case["given"])
        if issues:
            bad[seed] = f"validator: {issues[0]}"
        elif scenario == "duplicate_ids":
            assert not isinstance(deck, NoBid), "the scenario must produce a proposal"
            ids = [c.cv_id for c in deck.team]
            if len(set(ids)) != len(ids):
                bad[seed] = f"the same consultant listed {len(ids)} times: {ids}"
    assert not bad, f"{len(bad)} of {len(SEEDS)} seeds: {bad}"


def test_requirements_beyond_the_matrix_limit_are_not_dropped_silently():
    case = make_case("twenty_five_requirements", 0)
    trace = Trace()
    deck = compose(**case["kwargs"], llm=stand_in(), trace=trace)
    assert len(deck.requirements) < 25
    assert any("requirement" in w and "25" in w for w in bid_warnings(deck, trace)), (
        f"{25 - len(deck.requirements)} of 25 requirements are missing from the matrix and nothing says so")


# ---------- B2: adversarial models ----------

def run(mutate, *, ratio=0.6):
    trace, calls = Trace(), []
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, stand_in(ratio, mutate, calls), records=RECORDS,
                trace=trace, claim_check=True)
    return p, trace, bid_warnings(p, trace)


def only(step, change):
    return lambda s, r: change(r) if s == step else None


@pytest.mark.parametrize("ids", [["PRJ-9999"], ["CV-0002", "PRJ-9999"], ["x"]])
def test_citing_an_id_that_was_not_retrieved_is_rejected(ids):
    def cite(r):
        r["pillars"][1]["evidence"] = ids
    with pytest.raises(StepError, match="'summary'"):
        run(only("summary", cite))


def test_a_tampered_deck_citing_an_unretrieved_id_fails_validation(tmp_path):
    p, _, _ = run(None)
    p.requirements[0].evidence_id = "PRJ-9999"
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    assert any(i.kind == "unsupported claim" for i in validate(str(path), p, {"CV-0002"}))


@pytest.mark.parametrize("step,where", [
    ("brief", lambda r: r.update(price="€1")), ("letter", lambda r: r.update(delivered=True)),
    ("summary", lambda r: r["pillars"][0].update(score=0.99)),
    ("needs", lambda r: r["needs"][0].update(source="web")),
    ("evidence", lambda r: r.update(score=0.99)),
    ("approach", lambda r: r["phases"][0].update(price=10)),
])
def test_extra_keys_anywhere_in_a_reply_are_rejected(step, where):
    with pytest.raises(StepError, match=f"'{step}'"):
        run(only(step, where))


@pytest.mark.parametrize("step,field,make", [
    ("letter", "paragraphs", lambda r: r["paragraphs"] * 2),
    ("summary", "pillars", lambda r: r["pillars"] + r["pillars"][:1]),
    ("needs", "needs", lambda r: r["needs"] + r["needs"]),
    ("approach", "phases", lambda r: r["phases"] + r["phases"][:2]),
    ("brief", "key_messages", lambda r: r["key_messages"] + ["extra"]),
])
def test_lists_that_are_too_long_are_cut_and_flagged_never_passed_on(step, field, make):
    def grow(r):
        r[field] = make(r)
    p, trace, warnings = run(only(step, grow))
    entry = next(s for s in trace.steps if s["step"] == step)
    assert [t["how"] for t in entry["trimmed"]] == ["list"]
    assert any(w.startswith("1 list shortened by code") and f"{step}.{field}" in w for w in warnings)


@pytest.mark.parametrize("step,field", [("letter", "paragraphs"), ("approach", "phases")])
def test_an_empty_required_list_is_an_error_not_an_empty_slide(step, field):
    def empty(r):
        r[field] = []
    with pytest.raises(StepError, match=f"'{step}'"):
        run(only(step, empty))


INVENTED = [
    ("brief", lambda r: r["key_messages"].__setitem__(0, "In 2019 we delivered a 45% cost cut for Globex Corporation."),
     ['year "2019"', 'status "delivered"', 'percentage "45%"', 'name "Globex Corporation"'],
     "brief.key_messages[0]"),
    ("letter", lambda r: r["paragraphs"].__setitem__(0, "As ISO 27001 certified experts we saved Initech 3 million euros."),
     ['certification "ISO 27001"', 'status "certified"', 'money "3 million euros"'],
     "letter.paragraphs[0]"),
    ("summary", lambda r: r.update(why_us="Ranked first in Europe by Gartner in 2022, with 200 consultants."),
     ['year "2022"', 'number "200"'], "summary.why_us"),
    ("needs", lambda r: r["needs"][0].update(body="Your 14 hospitals need the Epic system, as at Mercy General."),
     ['number "14"', 'name "Mercy General"'], "needs.needs[0].body"),
    ("approach", lambda r: r["phases"][1].update(body="Deploy on Azure Kubernetes within 90 days."),
     ['name "Azure Kubernetes"', 'number "90"'], "approach.phases[1].body"),
    ("evidence", lambda r: r.update(line="Saved Initech 40% in 2020"),
     ['percentage "40%"', 'year "2020"'], "evidence.line"),
]


@pytest.mark.parametrize("step,change,claims,field", INVENTED, ids=[i[0] for i in INVENTED])
def test_invented_numbers_years_names_and_delivered_claims_are_flagged(step, change, claims, field):
    _, _, warnings = run(only(step, change))
    missing = [c for c in claims if f"unsupported {c} in {field}" not in warnings]
    assert not missing, f"not flagged: {missing}; got {[w for w in warnings if 'unsupported' in w]}"


def test_titles_and_labels_are_outside_the_claim_check():
    # By design (the check covers running text only): an invented client in a headline is not flagged.
    _, _, warnings = run(only("brief", lambda r: r.update(headline="Cost Savings Delivered For Globex")))
    assert not [w for w in warnings if w.startswith("unsupported")]


def test_a_status_the_model_may_not_set_cannot_be_set_by_prose():
    p, _, _ = run(only("summary", lambda r: r.update(why_us="Every project listed was delivered.")))
    assert not any(r.delivered for r in p.references if r.project_id == "olivesoft-027")
