"""What compose() does with inputs that cannot make a normal deck: it says so before
spending an LLM call, or it degrades in a way the sales manager is told about."""

from __future__ import annotations

import copy
import csv
import subprocess
import sys

import pytest
from pptx import Presentation

from proposal import build, export, render
from proposal.compose import InputError, StepError, Trace, bid_warnings, compose, retrieved_ids
from proposal.schemas import NoBid, Proposal
from proposal.tests.test_compose import (CVS, GAPS, PRJ, RECORDS, REPLIES, REQ, RESEARCH, TENDER, fake_llm,
                                         hit)
from proposal.validate import validate

IDEA = PRJ[0]


@pytest.fixture(autouse=True, scope="module")
def website_theme():
    render.apply_theme("website")


def summary_citing(cvs, prj):
    """A summary reply that cites only assets the model is actually given."""
    ids = list(dict.fromkeys(rid for h in [*cvs[:3], *prj[:3]]
                             if (rid := (h.get("metadata") or {}).get("record_id"))))
    reply = copy.deepcopy(REPLIES["summary"])
    for i, pillar in enumerate(reply["pillars"]):
        pillar["evidence"] = ids[i:i + 1]
    return [reply] * 3


def run(tender=TENDER, req=REQ, cvs=CVS, prj=PRJ, calls=None, **kw):
    llm = fake_llm({"summary": summary_citing(cvs, prj)}, calls=calls)
    return compose(tender, RESEARCH, req, cvs, prj, llm, records=RECORDS, **kw)


# ---------- the tender itself ----------

@pytest.mark.parametrize("field", ["title", "issuer"])
@pytest.mark.parametrize("bad", ["missing", "", "   ", None])
def test_a_tender_without_title_or_issuer_is_a_clear_error_before_any_llm_call(field, bad):
    tender = {k: v for k, v in TENDER.items() if k != field}
    if bad != "missing":
        tender[field] = bad
    calls = []
    with pytest.raises(InputError, match=f"tender.{field}"):
        run(tender=tender, calls=calls)
    assert calls == []


def test_a_tender_with_no_requirements_is_a_clear_error_before_any_llm_call():
    calls = []
    with pytest.raises(InputError, match="no requirements"):
        run(req={}, calls=calls)
    assert calls == []


# ---------- retrieval that is empty or malformed ----------

def test_no_cv_hits_gives_a_placeholder_team_and_a_warning():
    trace = Trace()
    p = run(cvs=[], trace=trace)
    assert [(c.cv_id, c.name, c.role, c.skills, c.score) for c in p.team] == [
        (None, "To be staffed", "Consultant for ETL pipelines", "ETL pipelines", 0.0)]
    warnings = bid_warnings(p, trace)
    assert "no CV matched: the team slide is a placeholder" in warnings
    assert "every matched consultant is a weak match" not in warnings


def test_no_project_hits_gives_a_placeholder_reference_and_a_warning():
    trace = Trace()
    p = run(prj=[], trace=trace)
    assert [(r.project_id, r.title, r.delivered) for r in p.references] == [(None, "No matching project", False)]
    warnings = bid_warnings(p, trace)
    assert "no project matched: the references slide is a placeholder" in warnings
    assert "no delivered reference project" not in warnings


def test_a_deck_with_placeholders_renders_and_validates(tmp_path):
    p = run(cvs=[], prj=[])
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    assert validate(str(path), p, retrieved_ids(p) | {"CV-0002", "PRJ-0003", "olivesoft-027"}) == []


@pytest.mark.parametrize("bad", [-0.2, 1.5, float("nan"), "0.5", True, None])
def test_a_similarity_outside_0_to_1_is_a_clear_error_before_any_llm_call(bad):
    req = copy.deepcopy(REQ)
    req["ETL pipelines"][1]["similarity"] = bad
    calls = []
    with pytest.raises(InputError, match=r"requirement 'ETL pipelines' hit PRJ-0003: similarity"):
        run(req=req, calls=calls)
    assert calls == []


def test_a_bad_similarity_in_the_cv_list_names_the_list():
    cv = {**CVS[0], "similarity": -0.1}
    with pytest.raises(InputError, match=r"cv_matches hit CV-0002: similarity -0.1 is outside 0..1"):
        run(cvs=[cv])


def test_float_noise_at_the_limits_is_clipped_not_an_error():
    req = copy.deepcopy(REQ)
    req["ETL pipelines"][1]["similarity"] = 1.0000001
    cv = {**CVS[0], "similarity": -1e-7}
    p = run(req=req, cvs=[cv])
    assert p.requirements[0].score == 1.0 and p.team[0].score == 0.0


@pytest.mark.parametrize("metadata", [{}, None, {"record_id": ""}])
def test_a_hit_without_a_record_id_is_an_error_not_a_guess_from_the_chunk_id(metadata):
    cv = {**CVS[0], "id": "9f1c-chunk-uuid", "metadata": metadata}
    with pytest.raises(InputError, match="9f1c-chunk-uuid.*metadata.record_id"):
        run(cvs=[cv])


# ---------- duplicates ----------

def test_duplicate_records_are_removed_before_anything_else():
    calls = []
    cv2 = hit("c5", "CV-0003", "cv", 0.8, person="Employee_003", role="BI", skills=["x"])
    p = run(cvs=[CVS[0], CVS[0], cv2, CVS[0]], prj=[PRJ[1], PRJ[1], IDEA, IDEA], calls=calls)
    assert [c.cv_id for c in p.team] == ["CV-0002", "CV-0003"]
    assert [r.project_id for r in p.references] == ["PRJ-0003", "olivesoft-027"]
    summary = next(payload for step, payload in calls if step == "summary")
    ids = [a["id"] for a in summary["ASSETS"]]
    assert len(ids) == len(set(ids))


# ---------- more requirements than the matrix shows ----------

def many(n=25):
    return {f"Requirement {i}": [hit(f"c{i}", f"PRJ-{i:04d}", "project", round(0.30 + i * 0.02, 2),
                                     f"content {i}")] for i in range(n)}


def test_more_requirements_than_the_matrix_shows_are_ranked_and_never_dropped_silently():
    calls, trace = [], Trace()
    p = run(req=many(), calls=calls, trace=trace)
    assert len(p.requirements) == 7 and len(p.all_requirements) == 25
    assert [r.requirement for r in p.requirements] == [f"Requirement {i}" for i in range(18, 25)]
    assert [c[0] for c in calls].count("evidence") == 7
    assert ("7 of 25 requirements shown; the full list is in the CSV; "
            "5 of the 18 hidden requirements are Gap") in bid_warnings(p, trace)


def test_up_to_seven_requirements_keep_the_tenders_order_and_raise_no_warning():
    p = run(req=many(7))
    assert [r.requirement for r in p.requirements] == [f"Requirement {i}" for i in range(7)]
    assert not [w for w in bid_warnings(p) if "requirements shown" in w]


def test_the_full_matrix_goes_to_a_csv(tmp_path):
    p = run(req=many())
    path = export.matrix_csv(p, tmp_path / "m.csv")
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert list(rows[0]) == ["requirement", "fit", "score", "evidence_id", "evidence", "shown"]
    assert len(rows) == 25 and [r["shown"] for r in rows].count("yes") == 7
    assert rows[0]["requirement"] == "Requirement 0" and rows[0]["fit"] == "Gap" and rows[0]["shown"] == "no"
    assert rows[24]["fit"] == "Strong" and rows[24]["evidence"] and rows[24]["evidence_id"] == "PRJ-0024"


# ---------- long names ----------

def test_a_very_long_issuer_never_overflows_the_footer(tmp_path):
    p = run(tender={**TENDER, "issuer": "x" * 400})
    path = tmp_path / "d.pptx"
    render.render(p, str(path))
    assert validate(str(path)) == []


# ---------- all Gap: the no-bid result ----------

WEAK = {"Allergen evidence": [hit("c4", "PRJ-0003", "project", 0.17, "Utility data hub")],
        "Catering": []}
WEAK_CV = [hit("c2", "CV-0002", "cv", 0.3)]


def test_when_every_row_is_a_gap_no_prose_is_requested_and_a_no_bid_result_comes_back():
    calls = []
    r = run(req=WEAK, cvs=WEAK_CV, prj=[IDEA], calls=calls)
    assert isinstance(r, NoBid) and calls == []
    assert [row.fit for row in r.requirements] == ["Gap", "Gap"]
    assert r.requirements[0].evidence == "Weak match only, flagged for review"
    assert r.warnings[0] == "no-bid recommendation: every requirement is a Gap (best match below 0.40)"
    assert r.warnings[1:] == [GAPS, "no requirement has strong evidence", "no delivered reference project",
                              "every matched consultant is a weak match"]
    assert bid_warnings(r) == r.warnings
    assert "0.40" in r.recommendation and "full proposal can still be generated" in r.recommendation


def test_force_bid_writes_the_full_proposal_anyway():
    calls = []
    p = run(req=WEAK, cvs=WEAK_CV, prj=[IDEA], calls=calls, force_bid=True)
    assert isinstance(p, Proposal) and [c[0] for c in calls][:2] == ["brief", "letter"]


def test_one_row_at_exactly_partial_is_enough_to_bid():
    req = {**WEAK, "Utility data": [hit("c9", "PRJ-0003", "project", 0.40, "Utility data hub")]}
    assert isinstance(run(req=req, cvs=WEAK_CV, prj=[IDEA]), Proposal)
    req["Utility data"][0]["similarity"] = 0.3949
    assert isinstance(run(req=req, cvs=WEAK_CV, prj=[IDEA]), NoBid)


def test_a_row_with_only_internship_ideas_counts_as_a_gap():
    req = {"Anything": [IDEA]}
    assert isinstance(run(req=req, cvs=WEAK_CV, prj=[IDEA]), NoBid)


def test_the_no_bid_deck_has_three_slides_and_says_why(tmp_path):
    r = run(req=WEAK, cvs=WEAK_CV, prj=[IDEA])
    path = tmp_path / "nb.pptx"
    render.render_no_bid(r, str(path))
    slides = Presentation(str(path)).slides
    text = [[sh.text_frame.text for sh in s.shapes if sh.has_text_frame] for s in slides]
    assert len(slides) == 3
    assert any("NO-BID RECOMMENDATION" in t for t in text[0])
    assert any(r.recommendation in t for t in text[2])
    assert any(r.warnings[1] in t for t in text[2])
    assert validate(str(path)) == []


# ---------- the validator blocks ----------

def broken(p):
    p.investment.note = "word " * 400
    return p


def test_a_deck_with_validator_issues_is_not_written(tmp_path):
    p = broken(run())
    path = tmp_path / "d.pptx"
    with pytest.raises(build.DeckRejected) as e:
        build.build(p, path)
    assert e.value.issues and "overflow" in str(e.value)
    assert list(tmp_path.iterdir()) == []


def test_allow_issues_writes_the_deck_and_puts_the_issues_in_the_bid_warnings(tmp_path):
    p = broken(run())
    built = build.build(p, tmp_path / "d.pptx", allow_issues=True)
    assert built.path.exists() and built.issues
    assert any(w.startswith("validator: slide 09") for w in built.warnings)


def test_a_clean_deck_is_written_with_its_matrix_csv(tmp_path):
    p = run()
    built = build.build(p, tmp_path / "d.pptx", retrieved={"CV-0002", "PRJ-0003", "olivesoft-027"})
    assert built.path.exists() and built.issues == []
    assert built.csv == tmp_path / "d.matrix.csv" and built.csv.exists()


def test_a_citation_the_retrieval_did_not_return_blocks_the_deck(tmp_path):
    p = run()
    with pytest.raises(build.DeckRejected, match="unsupported claim"):
        build.build(p, tmp_path / "d.pptx", retrieved={"CV-0002"})


def test_a_no_bid_result_is_built_too(tmp_path):
    built = build.build(run(req=WEAK, cvs=WEAK_CV, prj=[IDEA]), tmp_path / "nb.pptx")
    assert built.path.exists() and built.warnings[0].startswith("no-bid recommendation")


def cli(tmp_path, *extra):
    import json
    data = json.load(open("proposal/sample_maison_aurele.json", encoding="utf-8"))
    data["investment"]["note"] = "word " * 400
    src = tmp_path / "in.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out.pptx"
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "proposal", str(src), str(out), *extra],
                       capture_output=True, text=True)
    return r, out


def test_the_cli_exits_non_zero_and_writes_nothing_when_the_validator_objects(tmp_path):
    r, out = cli(tmp_path)
    assert r.returncode != 0 and "overflow" in r.stderr and not out.exists()


def test_the_cli_allow_issues_flag_writes_the_deck_and_prints_the_issues(tmp_path):
    r, out = cli(tmp_path, "--allow-issues")
    assert r.returncode == 0 and out.exists() and "validator: slide 09" in r.stdout


# ---------- invented citations ----------

def test_the_retry_after_an_invented_id_lists_the_exact_ids_it_may_cite():
    bad = copy.deepcopy(REPLIES["summary"])
    bad["pillars"][2]["evidence"] = ["CV-005"]
    calls = []
    compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"summary": [bad]}, calls=calls), records=RECORDS)
    first, retry = [payload for step, payload in calls if step == "summary"]
    assert "FIX_PREVIOUS_REPLY" not in first
    assert retry["FIX_PREVIOUS_REPLY"] == [
        "pillars[2].evidence cites CV-005, which is not one of your input assets; cite only these "
        "ids: ['CV-0002', 'PRJ-0003', 'olivesoft-027'], or leave the list empty"]


def test_a_near_miss_id_is_never_repaired_by_code():
    near = copy.deepcopy(REPLIES["summary"])
    near["pillars"][0]["evidence"] = ["CV-0003"]  # one digit off CV-0002
    with pytest.raises(StepError, match="'summary'.*CV-0003"):
        compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"summary": [near] * 3}), records=RECORDS)
