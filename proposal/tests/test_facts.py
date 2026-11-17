"""Facts that code, not the model, decides: statuses, scores, who is shown, what is cut."""

from __future__ import annotations

import copy
import json

import pytest

from proposal.compose import (InputError, StepError, approach_title, bid_warnings, compose,
                              is_delivered, load_records, record_id)
from proposal.config import Config
from proposal.schemas import fit_for
from proposal.tests.test_compose import (CVS, PRJ, RECORDS, REPLIES, REQ, RESEARCH, TENDER, fake_llm,
                                         hit)


def quiet_summary():
    reply = copy.deepcopy(REPLIES["summary"])
    for pillar in reply["pillars"]:
        pillar["evidence"] = []
    return [reply] * 3


def run(cvs=CVS, prj=PRJ, req=REQ, tender=TENDER, records=RECORDS, calls=None):
    llm = fake_llm({"summary": quiet_summary()}, calls=calls)
    return compose(tender, RESEARCH, req, cvs, prj, llm, records=records)


# ---------- delivered or not (F6) ----------

@pytest.mark.parametrize("rec,expected", [
    ({"outcome": "Delivered on schedule"}, None),
    ({"outcome": "Handed over to internal IT."}, None),
    ({"outcome": "Delivered on schedule; a planned follow-up phase"}, None),
    ({"outcome": "rollout was cancelled"}, None),
    ({"outcome": "contract terminated early"}, None),
    ({"outcome": "never reached production"}, None),
    ({"outcome": "shelved"}, None),
    ({"outcome": "Not completed"}, False),
    ({"outcome": "not yet delivered"}, False),
    ({"outcome": "Cancelled by the client"}, False),
    ({"outcome": "abandoned after phase 1"}, False),
    ({"outcome": "In progress"}, False),
    ({"outcome": "On hold"}, False),
    ({"outcome": "proposed"}, False),
    ({"outcome": ""}, None),
    ({"outcome": None}, None),
    ({}, None),
    ({"status": "completed", "outcome": "x"}, True),
    ({"status": "Cancelled", "outcome": "Delivered"}, False),
    ({"status": "in progress"}, False),
    ({"is_completed": True}, True),
    ({"is_completed": False, "outcome": "Handed over."}, False),
    ({"evidence_status": "proposed", "outcome": "Handed over."}, False),
    ({"evidence_status": "completed"}, True),
    ({"relationship": "pfe_internship_project", "status": "completed"}, False),
])
def test_is_delivered(rec, expected):
    assert is_delivered(rec) is expected


def test_unverified_projects_rank_above_pfe_ideas():
    p = run()
    assert [(r.project_id, r.delivered) for r in p.references] == [("PRJ-0003", None),
                                                                   ("olivesoft-027", False)]


# ---------- pricing ----------

def test_every_price_line_is_phase_weeks_times_team_times_day_rate():
    p = run()
    assert [(ln.workstream, ln.days, ln.amount) for ln in p.investment.lines] == [
        ("Discover", 20, 13000), ("Build", 60, 39000)]


def test_the_day_rate_and_team_size_come_from_the_config():
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ, fake_llm({"summary": quiet_summary()}),
                records=RECORDS, config=Config(day_rate=500, team_size=1))
    assert [(ln.days, ln.amount) for ln in p.investment.lines] == [(10, 5000), (30, 15000)]


def test_a_long_plan_warns_that_the_price_grows_with_it():
    long_plan = {"phases": [{"name": "Discover", "weeks": 10, "body": "Audit."},
                            {"name": "Build", "weeks": 20, "body": "Build."}]}
    p = compose(TENDER, RESEARCH, REQ, CVS, PRJ,
                fake_llm({"summary": quiet_summary(), "approach": [long_plan]}), records=RECORDS)
    assert "the plan runs 30 weeks, over 26: check the indicative price" in bid_warnings(p)
    assert not any("indicative price" in w for w in bid_warnings(run()))


# ---------- Strong / Partial / Gap ----------

@pytest.mark.parametrize("score,fit", [(1.0, "Strong"), (0.55, "Strong"), (0.5499, "Partial"),
                                       (0.40, "Partial"), (0.3999, "Gap"), (0.0, "Gap")])
def test_the_cutoffs_sit_where_the_report_says(score, fit):
    assert fit_for(score) == fit


def test_a_row_scored_at_the_cutoff_gets_that_label_in_a_deck():
    req = {"A": [hit("a", "PRJ-0003", "project", 0.55, "x")], "B": [hit("b", "PRJ-0003", "project", 0.40, "x")]}
    p = run(req=req)
    assert [r.fit for r in p.requirements] == ["Strong", "Partial"]


# ---------- who is shown ----------

def test_each_consultants_distinguishing_skills_come_first():
    cvs = [hit("a", "CV-1", "cv", 0.9), hit("b", "CV-2", "cv", 0.8)]
    records = {"CV-1": {"cv_id": "CV-1", "name": "A", "role": "r", "skills": ["Airflow", "dbt", "Spark"]},
               "CV-2": {"cv_id": "CV-2", "name": "B", "role": "r", "skills": ["Airflow", "dbt", "Kafka"]}}
    p = run(cvs=cvs, records=records)
    assert [c.skills for c in p.team] == ["Spark, Airflow, dbt", "Kafka, Airflow, dbt"]


def test_at_most_three_consultants_and_three_projects_are_shown():
    cvs = [hit(f"c{i}", f"CV-{i}", "cv", 0.9 - i / 10) for i in range(5)]
    prj = [hit(f"p{i}", f"PRJ-{i}", "project", 0.9 - i / 10) for i in range(5)]
    p = run(cvs=cvs, prj=prj, records={})
    assert [c.cv_id for c in p.team] == ["CV-0", "CV-1", "CV-2"]
    assert len(p.references) == 3


def test_the_model_sees_at_most_three_assets_of_each_kind():
    cvs = [hit(f"c{i}", f"CV-{i}", "cv", 0.9 - i / 10) for i in range(5)]
    prj = [hit(f"p{i}", f"PRJ-{i}", "project", 0.9 - i / 10) for i in range(5)]
    calls = []
    run(cvs=cvs, prj=prj, records={}, calls=calls)
    ids = [a["id"] for a in next(pl for step, pl in calls if step == "summary")["ASSETS"]]
    assert ids == ["CV-0", "CV-1", "CV-2", "PRJ-0", "PRJ-1", "PRJ-2"]


# ---------- only CV and project records are evidence ----------

def page(record_id, doc_type, original, similarity):
    """A fix/data-rag hit: the ingest folds website and client pages into cv/project/tool."""
    return hit(f"chunk-{record_id}", record_id, doc_type, similarity, f"{record_id} page",
               original_doc_type=original)


SERVICE = page("service-001", "tool", "tools_tech_stack", 0.95)
CLIENT = page("client-001", "project", "client_portfolio", 0.93)
REF_PAGE = page("project-001", "project", "project_reference", 0.91)
TOOL = hit("t1", "TOOL-1", "tool", 0.9)


def test_requirement_evidence_skips_pages_and_tools_that_are_not_cv_or_project_records():
    req = {"ETL pipelines": [SERVICE, TOOL, CLIENT, hit("c1", "PRJ-0003", "project", 0.62)]}
    row = run(req=req).requirements[0]
    assert (row.evidence_id, row.score) == ("PRJ-0003", 0.62)


def test_reference_cards_take_only_project_records():
    prj = [CLIENT, REF_PAGE, *PRJ]
    assert [r.project_id for r in run(prj=prj).references] == ["PRJ-0003", "olivesoft-027"]


def test_a_cv_slot_takes_only_cv_records():
    cvs = [page("company-001", "tool", "company_profile", 0.99), *CVS]
    assert [c.cv_id for c in run(cvs=cvs).team] == ["CV-0002"]


def test_website_and_client_pages_reach_only_the_summary_and_cannot_be_cited():
    calls = []
    run(prj=[CLIENT, REF_PAGE, *PRJ], calls=calls)
    seen = {step: pl for step, pl in calls}
    assert [a["id"] for a in seen["summary"]["COMPANY_PAGES"]] == ["client-001", "project-001"]
    assert {a["id"] for a in seen["summary"]["ASSETS"]}.isdisjoint({"client-001", "project-001"})
    assert all("COMPANY_PAGES" not in pl for step, pl in calls if step != "summary")


def test_a_summary_citing_a_company_page_is_rejected():
    cites_page = copy.deepcopy(REPLIES["summary"])
    cites_page["pillars"][0]["evidence"] = ["client-001"]
    llm = fake_llm({"summary": [cites_page] * 3})
    with pytest.raises(StepError, match="'summary'"):
        compose(TENDER, RESEARCH, REQ, CVS, [CLIENT, *PRJ], llm, records=RECORDS)


def test_without_company_pages_the_summary_payload_is_unchanged():
    calls = []
    run(calls=calls)
    assert set(next(pl for step, pl in calls if step == "summary")) == {"BRIEF", "ASSETS"}


# ---------- what the model is given is capped ----------

def test_the_tender_text_is_cut_at_3000_characters():
    calls = []
    run(tender={**TENDER, "raw_text": "x" * 5000}, calls=calls)
    assert len(next(pl for step, pl in calls if step == "brief")["TENDER"]["text"]) == 3000


def test_an_assets_text_is_cut_at_500_characters():
    req = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.87, "y" * 800)]}
    calls = []
    run(req=req, calls=calls)
    assert len(next(pl for step, pl in calls if step == "evidence")["ASSET"]["text"]) == 500


# ---------- reading the source records ----------

def test_load_records_reads_every_id_key_and_both_file_shapes(tmp_path):
    files = {"fake_cvs.json": [{"cv_id": "CV-1", "name": "A"}],
             "fake_projects.json": [{"project_id": "PRJ-1", "summary": "S"}],
             "olivesoft_projects.json": [{"id": "olivesoft-1", "name": "N"}],
             "fake_tools.json": {"tools": [{"tool_id": "TOOL-1", "name": "T"}]}}
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    records = load_records(tmp_path)
    assert set(records) == {"CV-1", "PRJ-1", "olivesoft-1", "TOOL-1"}
    assert records["TOOL-1"]["name"] == "T" and records["olivesoft-1"]["name"] == "N"


def test_record_id_reads_the_metadata_not_the_chunk_id():
    assert record_id({"id": "chunk-uuid", "metadata": {"record_id": "CV-7"}}) == "CV-7"
    with pytest.raises(InputError, match="chunk-uuid"):
        record_id({"id": "chunk-uuid", "metadata": {}})


# ---------- the approach title ----------

@pytest.mark.parametrize("n,title", [
    (1, "One phase, a working release at each"), (2, "Two phases, a working release at each"),
    (4, "Four phases, a working release at each"), (12, "Twelve phases, a working release at each"),
    (13, "13 phases, a working release at each")])
def test_the_approach_title_works_for_any_number_of_phases(n, title):
    assert approach_title(n) == title


def test_load_records_takes_another_datasets_file_names_and_client_ids(tmp_path):
    files = {"cvs_clean.json": [{"cv_id": "CV-1", "name": "A"}],
             "projects_clean.json": [{"project_id": "PRJ-1", "name": "P"}],
             "client_portfolio.json": [{"client_id": "CLIENT-1", "name": "C"}, {"name": "no id at all"}]}
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    records = load_records(tmp_path, files=tuple(files))
    assert set(records) == {"CV-1", "PRJ-1", "CLIENT-1"} and records["CLIENT-1"]["name"] == "C"


# ---------- an evidence line that disclaims its asset ----------

@pytest.mark.parametrize("line", ["Not applicable.", "N/A", "No relevant evidence.", "None",
                                  "Not relevant to this requirement", "Does not show FHIR work."])
def test_an_evidence_line_that_disclaims_its_asset_is_replaced_by_code_and_flagged(line):
    req = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.46, "x")]}
    p = compose(TENDER, RESEARCH, req, CVS, PRJ, fake_llm({"evidence": [{"line": line}]}),
                records=RECORDS)
    row = p.requirements[0]
    assert (row.evidence, row.score, row.evidence_id) == (
        "Related asset only, flagged for review", 0.46, "PRJ-0003")
    assert f'evidence for "ETL pipelines" disclaimed by the model: "{line}"' in bid_warnings(p)


def test_an_ordinary_evidence_line_is_kept():
    req = {"ETL pipelines": [hit("c1", "PRJ-0003", "project", 0.46, "x")]}
    p = compose(TENDER, RESEARCH, req, CVS, PRJ, fake_llm({"evidence": [{"line": "None of the gaps; a hub"}]}),
                records=RECORDS)
    assert p.requirements[0].evidence == "None of the gaps; a hub"
