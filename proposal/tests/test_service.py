"""proposal.main: the HTTP contract, replayed with a fake LLM, a stub RAG, no
side-loaded records and no LibreOffice. The posted cv/project hits embed their
source record in metadata, the way rag.ingest_json builds them and n8n posts
them; the per-requirement queries are the service's own."""

import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import proposal.main as service
from proposal.compose import TASKS
from proposal.schemas import Meta, NoBid, RequirementRow
from proposal.tests.test_compose import REPLIES, TENDER
from shared import store
from shared.errors import ApiError, ErrorCode
from shared.schemas import ProspectResearch, Tender

TOKEN = {"X-Internal-Token": "super-token"}
TENDER_ID = "tender-001"


def stored_tender(**overrides):
    fields = dict(id=TENDER_ID, title=TENDER["title"], issuer=TENDER["issuer"],
                  sector="Data Integration", requirements=TENDER["requirements"],
                  raw_text=TENDER["raw_text"], source="simulated_feed",
                  detected_at=datetime.now(timezone.utc), status="new")
    fields.update(overrides)
    return Tender(**fields)


def stored_research():
    return ProspectResearch(
        tender_id=TENDER_ID, issuer=TENDER["issuer"], sector="Water utility",
        estimated_revenue="not stated", past_projects=[], key_partners=["Ministry"],
        notes="n", confidence="medium", sources=[], status="complete")


def team_bundle():
    """The request body n8n posts: only the team matches, records in metadata."""
    return {"cv_matches": META_CVS, "project_matches": META_PRJ}


# The posted metadata carries the fact fields, no "Cvs dataset" lookup happens.
META_CVS = [{"id": "c1", "content": "", "doc_type": "cv", "source_file": "x.json",
             "metadata": {"record_id": "CV-0002", "name": "Employee_002",
                          "person": "Employee_002", "role": "Data engineer",
                          "years_experience": 7, "skills": ["Airflow", "dbt"]},
             "similarity": 0.9, "ranking_score": 0.9}]
META_PRJ = [{"id": "c2", "content": "", "doc_type": "project", "source_file": "x.json",
             "metadata": {"record_id": "PRJ-0003", "name": "Central data hub",
                          "summary": "Central data hub", "client_sector": "utilities",
                          "outcome": "Handed over to internal IT."},
             "similarity": 0.87, "ranking_score": 0.87}]
# What the rag service answers, one query per requirement.
REQ_HITS = {"ETL pipelines": [META_PRJ[0]],
            "Arabic training": []}


class FakeAdapter:
    """compose()'s llm(system, user): the recorded replies, one per step, counted."""

    calls: list[dict] = []

    def __init__(self, *a, **k):
        pass

    def __call__(self, system, user):
        step = next(k for k in REPLIES if system.endswith(TASKS[k]))
        reply = json.dumps(REPLIES[step])
        FakeAdapter.calls.append({"step": step, "reply": reply})
        return reply


class FakeJudge:
    """The grounding verifier's judge: one 'partial' verdict per field it is asked about."""

    def __init__(self, seen):
        self.seen = seen

    def __call__(self, system, user):
        fields = json.loads(user)["FIELDS"]
        self.seen.append(user)
        return json.dumps({"verdicts": [{"field": f["field"], "verdict": "partial",
                                         "reason": "says less"} for f in fields]})


class FailingJudge:
    """A judge whose provider refuses every call."""

    def __call__(self, system, user):
        raise RuntimeError("model not found")



def missing_soffice(pptx, outdir=None, timeout=180):
    raise FileNotFoundError("LibreOffice not found; set SOFFICE_PATH")


class FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code

    def json(self):
        return []


class FakeRag:
    """An httpx.Client-shaped stub answering /query with queued statuses."""

    def __init__(self, statuses):
        self.statuses = list(statuses)

    def post(self, url, headers=None, json=None):
        return FakeResp(self.statuses.pop(0) if self.statuses else 500)


def rag_search(client, token, query, top_k, doc_type):
    """The canned hits for the service's own per-requirement queries."""
    return REQ_HITS.get(query, [])


@pytest.fixture
def service_env(monkeypatch, tmp_path):
    """Isolated service: token env, tmp db and output dir, canned provider."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "super-token")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(service, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(store, "get_tender",
                        lambda tid: stored_tender() if tid == TENDER_ID else None)
    monkeypatch.setattr(store, "get_research",
                        lambda tid: stored_research() if tid == TENDER_ID else None)
    monkeypatch.setattr(service, "Adapter", FakeAdapter)
    monkeypatch.setattr(service, "_search", rag_search)
    # a developer .env that names a verifier model must not turn these tests
    # into live judge calls; every verifier test opts back in explicitly
    monkeypatch.delenv("PROPOSAL_VERIFIER_LLM_MODEL", raising=False)
    FakeAdapter.calls.clear()
    return tmp_path


def test_a_post_writes_deck_matrix_and_result_and_the_get_reads_it(service_env, monkeypatch):
    def missing_soffice(pptx, outdir=None, timeout=180):
        raise FileNotFoundError("LibreOffice not found; set SOFFICE_PATH")
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tender_id"] == TENDER_ID and body["kind"] == "proposal"
        assert body["deck"]["meta"]["buyer"] == TENDER["issuer"]
        # the team card's facts come straight from the hit metadata
        assert (body["deck"]["team"][0]["name"], body["deck"]["team"][0]["years"]) \
            == ("Employee_002", 7)
        assert body["artifacts"]["pdf"] is None  # no LibreOffice
        assert any(w.startswith("PDF skipped") for w in body["warnings"])
        assert {c["step"] for c in FakeAdapter.calls} == set(REPLIES)
        assert (service_env / f"{TENDER_ID}.pptx").is_file()
        assert (service_env / f"{TENDER_ID}.matrix.csv").is_file()
        assert (service_env / f"{TENDER_ID}.json").is_file()
        g = client.get(f"/proposal/{TENDER_ID}", headers=TOKEN)
        assert g.status_code == 200 and g.json()["deck"]["meta"]["buyer"] == "Sonede"


def test_one_rag_query_per_requirement_and_no_team_query(service_env, monkeypatch):
    queries = []

    def spy(client, token, query, top_k, doc_type):
        queries.append((query, doc_type))
        return rag_search(client, token, query, top_k, doc_type)

    monkeypatch.setattr(service, "_search", spy)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200
    # exactly one query per tender requirement, pulled with the tender itself;
    # cv/project matches come from the body, never the service
    assert sorted(queries) == sorted((req, None) for req in TENDER["requirements"])


def test_a_too_short_requirement_skips_the_query_and_scores_a_gap(service_env, monkeypatch):
    monkeypatch.setattr(store, "get_tender",
                        lambda tid: stored_tender(id=tid, requirements=["AI", "ETL pipelines"]))
    queries = []

    def spy(client, token, query, top_k, doc_type):
        queries.append(query)
        return rag_search(client, token, query, top_k, doc_type)

    monkeypatch.setattr(service, "_search", spy)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200
    rows = {row["requirement"]: row for row in r.json()["deck"]["all_requirements"]}
    assert rows["AI"]["evidence_id"] is None  # a Gap row, not a failed request
    assert queries == ["ETL pipelines"]  # "AI" was never sent to the rag service


def test_a_search_that_finds_nothing_scores_a_gap(service_env, monkeypatch):
    monkeypatch.setattr(service, "_search",
                        lambda client, token, query, top_k, doc_type: [])
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        rows = {row["requirement"]: row for row in r.json()["deck"]["all_requirements"]}
        assert rows["ETL pipelines"]["evidence_id"] is None
        assert rows["Arabic training"]["evidence_id"] is None


def test_a_rag_500_maps_to_a_retryable_upstream_envelope(service_env, monkeypatch):
    def broken(client, token, query, top_k, doc_type):
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, "retrieval unavailable (HTTP 500)",
                       status_code=503, retryable=True)
    monkeypatch.setattr(service, "_search", broken)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 503
        err = r.json()["error"]
        assert err["code"] == "UPSTREAM_UNAVAILABLE" and err["retryable"] is True


def test_search_maps_the_rag_statuses():
    rag = FakeRag([200])
    assert service._search(rag, "super-token", "query", 5, None) == []
    with pytest.raises(ApiError) as e:
        service._search(FakeRag([503]), "super-token", "q", 5, None)
    assert e.value.status_code == 503 and e.value.retryable
    with pytest.raises(ApiError) as e:
        service._search(FakeRag([400]), "super-token", "q", 5, None)
    assert e.value.status_code == 400
    with pytest.raises(ApiError) as e:
        service._search(FakeRag([401]), "super-token", "q", 5, None)
    assert "token" in e.value.message


def _search(client, token, query, top_k, doc_type):
    from proposal.main import RAG_URL  # noqa: F401  (real function re-bound below)
    return service._search.__wrapped__(client, token, query, top_k, doc_type) \
        if hasattr(service._search, "__wrapped__") else None


def test_weak_retrieval_recommends_a_no_bid_without_a_model_call(service_env, monkeypatch):
    def weak(client, token, query, top_k, doc_type):
        return [META_PRJ[0] | {"similarity": 0.2}]
    monkeypatch.setattr(service, "_search", weak)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "no_bid"
        assert NoBid.model_validate(body["deck"]).recommendation
        assert "no-bid recommendation" in body["warnings"][0]
        assert FakeAdapter.calls == []  # the no-bid gate spends no model budget


def test_checks_report_what_ran(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "verifier_call", lambda: (None, None))
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", headers=TOKEN,
                        json={**team_bundle(), "claim_check": True}).json()
        plain = client.post(f"/proposal/{TENDER_ID}", headers=TOKEN, json=team_bundle()).json()
    assert r["checks"] == {"verifier": False, "claim_check": True}
    assert plain["checks"] == {"verifier": False, "claim_check": False}


def test_verifier_runs_when_configured(service_env, monkeypatch):
    seen = []
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "verifier_call", lambda: ("judge-model", FakeJudge(seen)))
    monkeypatch.setattr(service, "same_model_note", lambda model: None)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
    assert r["checks"]["verifier"] is True and seen  # the judge was called
    assert any(w.startswith("verifier: partial support in ") for w in r["warnings"])


def test_a_judge_that_never_delivers_is_not_reported_as_run(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "verifier_call", lambda: ("judge-model", FailingJudge()))
    monkeypatch.setattr(service, "same_model_note", lambda model: None)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
    assert r["kind"] == "proposal"
    assert r["checks"]["verifier"] is False
    assert any(w.startswith("grounding check unavailable: ") for w in r["warnings"])


def test_one_failed_step_means_the_verifier_did_not_fully_run(service_env, monkeypatch):
    seen = []

    class Flaky(FakeJudge):
        def __call__(self, system, user):
            if json.loads(user)["STEP"] == "letter":
                raise RuntimeError("quota")
            return super().__call__(system, user)

    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "verifier_call", lambda: ("judge-model", Flaky(seen)))
    monkeypatch.setattr(service, "same_model_note", lambda model: None)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
    assert seen and r["checks"]["verifier"] is False
    assert any(w.startswith("grounding check unavailable: letter") for w in r["warnings"])


def test_a_no_bid_reports_no_check_and_no_same_model_note(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "_search", lambda client, token, query, top_k, doc_type:
                        [META_PRJ[0] | {"similarity": 0.2}])
    monkeypatch.setattr(service, "verifier_call", lambda: ("writer-model", FakeJudge([])))
    monkeypatch.setattr(service, "same_model_note", lambda model: f"same model {model}")
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", headers=TOKEN,
                        json={**team_bundle(), "claim_check": True}).json()
    assert r["kind"] == "no_bid"
    assert r["checks"] == {"verifier": False, "claim_check": False}
    assert "same model writer-model" not in r["warnings"]


def test_the_same_model_note_reaches_a_rejected_result(service_env, monkeypatch):
    from proposal.build import DeckRejected

    def reject(deck, path, **kw):
        raise DeckRejected([{"where": "slide 03", "what": "text overflow: warnings"}])

    monkeypatch.setattr(service, "build", reject)
    monkeypatch.setattr(service, "verifier_call", lambda: ("writer-model", FakeJudge([])))
    monkeypatch.setattr(service, "same_model_note", lambda model: f"same model {model}")
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
    assert r["kind"] == "rejected" and "same model writer-model" in r["warnings"]


def test_the_same_model_note_becomes_a_warning(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "verifier_call", lambda: ("writer-model", FakeJudge([])))
    monkeypatch.setattr(service, "same_model_note", lambda model: f"same model {model}")
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
    assert "same model writer-model" in r["warnings"]


def test_no_verifier_note_when_the_verifier_is_off(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "verifier_call", lambda: (None, None))
    monkeypatch.setattr(service, "same_model_note", lambda model: "must not be asked")
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
    assert not any("must not be asked" in w for w in r["warnings"])


def test_result_carries_the_trace(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
        stored = client.get(f"/proposal/{TENDER_ID}", headers=TOKEN).json()
    assert r["trace"] and all({"step", "attempts", "ok"} <= s.keys() for s in r["trace"])
    assert stored["trace"] == r["trace"]


def test_a_stored_result_from_before_the_trace_reads_empty(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    with TestClient(service.app) as client:
        client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        path = service_env / f"{TENDER_ID}.json"
        old = json.loads(path.read_text(encoding="utf-8"))
        del old["trace"]
        path.write_text(json.dumps(old), encoding="utf-8")
        g = client.get(f"/proposal/{TENDER_ID}", headers=TOKEN)
    assert g.status_code == 200 and g.json()["trace"] == []


def test_a_stored_result_from_before_checks_still_reads(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    with TestClient(service.app) as client:
        client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        path = service_env / f"{TENDER_ID}.json"
        old = json.loads(path.read_text(encoding="utf-8"))
        del old["checks"]
        path.write_text(json.dumps(old), encoding="utf-8")
        g = client.get(f"/proposal/{TENDER_ID}", headers=TOKEN)
    assert g.status_code == 200 and g.json()["checks"] == {}


def test_force_bid_turns_a_no_bid_into_a_proposal(service_env, monkeypatch):
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    monkeypatch.setattr(service, "_search", lambda client, token, query, top_k, doc_type:
                        [META_PRJ[0] | {"similarity": 0.2}])
    with TestClient(service.app) as client:
        refused = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
        assert refused["kind"] == "no_bid" and FakeAdapter.calls == []
        r = client.post(f"/proposal/{TENDER_ID}", headers=TOKEN,
                        json={**team_bundle(), "force_bid": True})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "proposal"
    assert FakeAdapter.calls  # forcing the bid spends the model budget


def test_the_flags_must_be_booleans(service_env):
    with TestClient(service.app) as client:
        for field in ("force_bid", "claim_check"):
            r = client.post(f"/proposal/{TENDER_ID}", headers=TOKEN,
                            json={**team_bundle(), field: "yes"})
            assert r.status_code == 422, field


def test_a_posted_hit_without_a_record_id_is_a_bad_request(service_env):
    body = team_bundle()
    body["cv_matches"] = [{"id": "c", "content": "", "metadata": {}, "similarity": 0.9}]
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=body, headers=TOKEN)
        assert r.status_code == 400 and "record_id" in r.json()["error"]["message"]


def test_a_posted_hit_with_a_similarity_outside_0_1_is_a_bad_request(service_env):
    body = team_bundle()
    body["project_matches"] = [{"id": "c", "content": "",
                                "metadata": {"record_id": "X-1"}, "similarity": 1.4}]
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=body, headers=TOKEN)
        assert r.status_code == 400


def test_a_tender_without_requirements_is_a_bad_request(service_env, monkeypatch):
    monkeypatch.setattr(store, "get_tender",
                        lambda tid: stored_tender(id=tid, requirements=[]))
    with TestClient(service.app) as client:
        r = client.post("/proposal/empty-1", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 400 and "requirements" in r.json()["error"]["message"]


def test_a_rejected_deck_answers_200_with_the_issues_and_writes_nothing(service_env, monkeypatch):
    # The validator gate means "no pptx written", not a failed call: the
    # composition succeeded, so the caller gets the composed deck back with
    # every issue in warnings (kind "rejected"), not a 422 that dead-ends n8n.
    from proposal.build import DeckRejected
    def reject(deck, path, **kw):
        raise DeckRejected([{"where": "slide 03", "what": "text overflow: warnings"}])
    monkeypatch.setattr(service, "build", reject)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200
        out = r.json()
        assert out["kind"] == "rejected" and out["artifacts"] == {}
        assert "slide 03" in out["warnings"][0] and "no deck written" in out["warnings"][0]
        assert out["deck"]  # the composed deck is still returned
        assert not service_env.joinpath(f"{TENDER_ID}.json").exists()
        assert not service_env.joinpath(f"{TENDER_ID}.pptx").exists()


def test_get_before_any_generation_is_404(service_env):
    with TestClient(service.app) as client:
        r = client.get("/proposal/tender-999", headers=TOKEN)
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_an_unknown_tender_is_404_in_the_envelope(service_env):
    with TestClient(service.app) as client:
        r = client.post("/proposal/tender-999", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
        assert "request_id" in r.json()["error"]


def test_without_the_token_everything_is_401(service_env):
    with TestClient(service.app) as client:
        assert client.get(f"/proposal/{TENDER_ID}").status_code == 401
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle())
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


def test_an_id_with_a_path_separator_never_reaches_generation(service_env):
    with TestClient(service.app) as client:
        r = client.post("/proposal/bad/id", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 404
        assert not (service_env / "bad.json").exists()


class FakeJudge:
    """Verifier.verify's judge: answers unsupported for every field, in the
    exact FIELDS order the prompt offered, in the rail-checked reply schema."""

    def __init__(self, *a, **k):
        self.calls: list[dict] = []

    def __call__(self, system, user):
        fields = [f["field"] for f in json.loads(user)["FIELDS"]]
        self.calls.append({"step_fields": fields})
        return json.dumps({"verdicts": [
            {"field": f, "verdict": "unsupported", "reason": "not in the sources"}
            for f in fields]})


def test_a_configured_judge_reads_every_checked_prose_field(service_env, monkeypatch):
    # the compose-level wiring: after each accepted step, its own judge re-reads
    # the same payload the writer saw; unsupported rows surface as warnings and
    # nothing else about the run changes
    judge = FakeJudge()
    monkeypatch.setattr(service, "verifier_call", lambda: ("fake-critic", judge))
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "proposal"
        assert body["deck"]["meta"]["buyer"] == TENDER["issuer"]
    rows = [w for w in body["warnings"] if w.startswith("verifier: unsupported claim in ")]
    # one row per judged field, every one carrying the judge's reason
    assert len(rows) == sum(len(s["step_fields"]) for s in judge.calls) and rows
    assert all(w.endswith(": not in the sources") for w in rows)
    assert not any(w == "verifier: off (no PROPOSAL_VERIFIER_LLM_MODEL)"
                   for w in body["warnings"])
    assert not any(w.startswith("grounding check unavailable") for w in body["warnings"])
    # the stored result the GET serves carries the same verdict rows
    g = json.loads((service_env / f"{TENDER_ID}.json").read_text(encoding="utf-8"))
    assert sum(w.startswith("verifier: unsupported claim in ") for w in g["warnings"]) \
        == len(rows)


def test_without_a_verifier_model_the_run_says_why_it_has_no_verdicts(service_env):
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200
    warnings = r.json()["warnings"]
    assert warnings.count("verifier: off (no PROPOSAL_VERIFIER_LLM_MODEL)") == 1
    assert not any(w.startswith(("verifier: unsupported", "verifier: partial",
                                 "grounding check unavailable")) for w in warnings)


def test_a_judge_on_the_writers_model_warns_of_shared_blind_spots(service_env, monkeypatch):
    monkeypatch.setattr(service, "verifier_call",
                        lambda: ("writer-model", FakeJudge()))
    monkeypatch.setenv("PROPOSAL_LLM_MODEL", "writer-model")
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200
    assert any("share the writer's blind spots" in w for w in r.json()["warnings"])


def test_a_dead_judge_never_fails_the_deck(service_env, monkeypatch):
    def dead_judge(system, user):
        raise RuntimeError("provider 500")
    monkeypatch.setattr(service, "verifier_call", lambda: ("dead-critic", dead_judge))
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200, r.text
        body = r.json()
    assert body["kind"] == "proposal" and body["deck"]["meta"]["buyer"] == TENDER["issuer"]
    assert any(w.startswith("grounding check unavailable: ")
               for w in body["warnings"])


def test_a_rejected_deck_still_tells_why_no_verdicts(service_env, monkeypatch):
    from proposal.build import DeckRejected
    def reject(deck, path, **kw):
        raise DeckRejected([{"where": "slide 03", "what": "text overflow: warnings"}])
    monkeypatch.setattr(service, "build", reject)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 200
        out = r.json()
    assert out["kind"] == "rejected"
    assert out["warnings"][0].startswith("no deck written")
    assert out["warnings"][-1] == "verifier: off (no PROPOSAL_VERIFIER_LLM_MODEL)"


def test_a_failed_step_is_logged_with_its_last_reply(service_env, monkeypatch, caplog):
    # The 503 diagnosis needs the offending model reply; the adapter records
    # every reply, and the step failure logs the last one before re-raising.
    def broken_letter_reply_step(*a, **k):
        pass

    class FailingAdapter(FakeAdapter):
        # reject the letter step three times: run_step gives up with StepError
        def __call__(self, system, user):
            step = next(k for k in REPLIES if system.endswith(TASKS[k]))
            if step == "letter":
                reply = "I am happy to help."
                FakeAdapter.calls.append({"step": step, "reply": reply})
                return reply
            return super().__call__(system, user)

    monkeypatch.setattr(service, "Adapter", FailingAdapter)
    with TestClient(service.app) as client:
        with caplog.at_level("WARNING", logger="proposal.main"):
            r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.status_code == 503
        err = r.json()["error"]
        assert err["code"] == "UPSTREAM_UNAVAILABLE" and "letter" in err["message"]
        assert "letter" in caplog.text
        assert "I am happy to help." in caplog.text  # the offending reply is kept



PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _post_deck(client, monkeypatch):
    def missing_soffice(pptx, outdir=None, timeout=180):
        raise FileNotFoundError("LibreOffice not found; set SOFFICE_PATH")
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
    assert r.status_code == 200, r.text
    return r.json()["artifacts"]


def test_files_serve_a_listed_artifact(service_env, monkeypatch):
    with TestClient(service.app) as client:
        artifacts = _post_deck(client, monkeypatch)
        pptx = client.get(f"/proposal/{TENDER_ID}/files/{artifacts['pptx']}", headers=TOKEN)
        assert pptx.status_code == 200
        assert pptx.content.startswith(b"PK")
        assert pptx.headers["content-type"] == PPTX_TYPE
        assert pptx.headers["content-disposition"].startswith("attachment")
        assert artifacts["pptx"] in pptx.headers["content-disposition"]
        csv = client.get(f"/proposal/{TENDER_ID}/files/{artifacts['csv']}", headers=TOKEN)
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        assert "attachment" in csv.headers["content-disposition"]


def test_files_serve_the_pdf_when_listed(service_env, monkeypatch):
    def fake_pdf(pptx, outdir=None, timeout=180):
        out = pptx.with_suffix(".pdf")
        out.write_bytes(b"%PDF-1.4 fake")
        return out
    monkeypatch.setattr(service, "to_pdf", fake_pdf)
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN)
        assert r.json()["artifacts"]["pdf"] == f"{TENDER_ID}.pdf"
        pdf = client.get(f"/proposal/{TENDER_ID}/files/{TENDER_ID}.pdf", headers=TOKEN)
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
        assert pdf.content == b"%PDF-1.4 fake"


def test_files_refuse_unlisted_names_and_traversal(service_env, monkeypatch):
    (service_env / "olivesoft.db").write_bytes(b"SQLite format 3")
    with TestClient(service.app) as client:
        _post_deck(client, monkeypatch)
        for name in ("olivesoft.db", "..%2F..%2F.env", "%2E%2E", "%2E", "%2e%2e%2f.env",
                     f"{TENDER_ID}.json", f"{TENDER_ID}.pdf", "missing.pptx"):
            r = client.get(f"/proposal/{TENDER_ID}/files/{name}", headers=TOKEN)
            assert r.status_code == 404, name
            assert r.json()["error"]["code"] == "NOT_FOUND", name
            assert "SQLite" not in r.text


def test_files_refuse_a_listed_name_that_escapes_the_output_dir(service_env, monkeypatch):
    out = service_env / "out"
    out.mkdir()
    (service_env / "outside.txt").write_text("SECRET=1")
    stored = service.ProposalResult(
        tender_id=TENDER_ID, kind="proposal", deck={}, warnings=[],
        artifacts={"pptx": "../outside.txt"}, generated_at="2026-01-01T00:00:00+00:00")
    (out / f"{TENDER_ID}.json").write_text(stored.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(service, "OUTPUT_DIR", out)
    with TestClient(service.app) as client:
        for name in ("..%2Foutside.txt", "../outside.txt"):
            r = client.get(f"/proposal/{TENDER_ID}/files/{name}", headers=TOKEN)
            assert r.status_code == 404 and "SECRET" not in r.text


def test_files_404_without_a_stored_result_and_400_for_a_bad_id(service_env):
    (service_env / "x.pptx").write_bytes(b"PK")
    with TestClient(service.app) as client:
        r = client.get(f"/proposal/{TENDER_ID}/files/x.pptx", headers=TOKEN)
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
        r = client.get("/proposal/bad%20id/files/x.pptx", headers=TOKEN)
        assert r.status_code == 400 and r.json()["error"]["field"] == "tender_id"


def test_files_need_the_internal_token(service_env, monkeypatch):
    with TestClient(service.app) as client:
        artifacts = _post_deck(client, monkeypatch)
        r = client.get(f"/proposal/{TENDER_ID}/files/{artifacts['pptx']}")
        assert r.status_code in (401, 403)


def _post_with_settings(client, monkeypatch, settings):
    def missing_soffice(pptx, outdir=None, timeout=180):
        raise FileNotFoundError("LibreOffice not found; set SOFFICE_PATH")
    monkeypatch.setattr(service, "to_pdf", missing_soffice)
    return client.post(f"/proposal/{TENDER_ID}", headers=TOKEN,
                       json={**team_bundle(), "settings": settings})


def test_settings_override_day_rate_and_team(service_env, monkeypatch):
    with TestClient(service.app) as client:
        r = _post_with_settings(client, monkeypatch, {"day_rate": 700, "team_size": 3})
        assert r.status_code == 200, r.text
        lines = r.json()["deck"]["investment"]["lines"]
    assert lines and all(l["amount"] == l["days"] * 700 for l in lines)
    default_days = sum(l["days"] for l in lines) / 3
    with TestClient(service.app) as client:
        base = client.post(f"/proposal/{TENDER_ID}", json=team_bundle(), headers=TOKEN).json()
    assert sum(l["days"] for l in base["deck"]["investment"]["lines"]) / 2 == default_days


def test_settings_override_text_fields_and_keep_unset_signatory_fields(service_env, monkeypatch):
    with TestClient(service.app) as client:
        r = _post_with_settings(client, monkeypatch, {
            "signatory_name": "Amel Ben Salah", "letter_title": "Your data partner",
            "currency": "TND", "investment_note": "Fixed price after scoping."})
        assert r.status_code == 200, r.text
        deck = r.json()["deck"]
    assert deck["signatory"] == {"name": "Amel Ben Salah", "role": "Sales, OliveSoft",
                                 "contact": "olivesoft.fr"}
    assert deck["letter"]["title"] == "Your data partner"
    assert deck["investment"]["currency"] == "TND"
    assert deck["investment"]["note"] == "Fixed price after scoping."


def test_no_settings_keeps_the_defaults(service_env, monkeypatch):
    with TestClient(service.app) as client:
        r = _post_with_settings(client, monkeypatch, None)
        assert r.status_code == 200, r.text
        deck = r.json()["deck"]
    assert deck["signatory"]["name"] == "OliveSoft Sales Team"
    assert deck["investment"]["currency"] == "€"


def test_unknown_setting_is_refused(service_env):
    with TestClient(service.app) as client:
        r = client.post(f"/proposal/{TENDER_ID}", headers=TOKEN,
                        json={"settings": {"margin": 0.4}})
    assert r.status_code == 422


def test_out_of_range_settings_are_refused(service_env):
    with TestClient(service.app) as client:
        for settings in ({"day_rate": 0}, {"day_rate": -5}, {"team_size": 0},
                         {"team_size": 1.5}, {"signatory_name": ""}):
            r = client.post(f"/proposal/{TENDER_ID}", headers=TOKEN,
                            json={"settings": settings})
            assert r.status_code == 422, settings


GENERATED_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def service_env_with_deck(service_env):
    stored = service.ProposalResult(
        tender_id=TENDER_ID, kind="proposal", deck={}, warnings=[],
        artifacts={}, generated_at=GENERATED_AT)
    (service_env / f"{TENDER_ID}.json").write_text(stored.model_dump_json(), encoding="utf-8")
    return service_env


def put_review(client, **fields):
    body = {"deck_generated_at": GENERATED_AT, **fields}
    return client.put(f"/proposal/{TENDER_ID}/review", json=body, headers=TOKEN)


def test_review_starts_empty_for_the_current_deck(service_env_with_deck):
    with TestClient(service.app) as client:
        r = client.get(f"/proposal/{TENDER_ID}/review", headers=TOKEN)
    assert r.json() == {"deck_generated_at": GENERATED_AT, "sections": {},
                        "signed_off_by": None, "signed_off_at": None}


def test_review_round_trip(service_env_with_deck):
    with TestClient(service.app) as client:
        put = put_review(client, sections={"summary": "approved"}, signed_off_by="  Ama  ")
        got = client.get(f"/proposal/{TENDER_ID}/review", headers=TOKEN).json()
    assert put.status_code == 200
    assert got["sections"] == {"summary": "approved"}
    assert got["signed_off_by"] == "Ama" and got["signed_off_at"]


def test_review_keeps_the_sign_off_time_until_the_name_changes(service_env_with_deck):
    with TestClient(service.app) as client:
        first = put_review(client, signed_off_by="Ama").json()
        again = put_review(client, sections={"team": "work"}, signed_off_by="Ama").json()
        cleared = put_review(client).json()
    assert again["signed_off_at"] == first["signed_off_at"]
    assert cleared["signed_off_by"] is None and cleared["signed_off_at"] is None


def test_review_for_an_older_deck_is_refused(service_env_with_deck):
    with TestClient(service.app) as client:
        r = client.put(f"/proposal/{TENDER_ID}/review", headers=TOKEN,
                       json={"deck_generated_at": "2020-01-01T00:00:00+00:00"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BAD_REQUEST"
    assert r.json()["error"]["message"] == "The deck was regenerated; reload the review"


@pytest.mark.parametrize("sections", [{"pricing": "approved"}, {"summary": "done"}])
def test_review_refuses_unknown_sections_and_statuses(service_env_with_deck, sections):
    with TestClient(service.app) as client:
        assert put_review(client, sections=sections).status_code == 422


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_review_refuses_a_bad_sign_off_name(service_env_with_deck, name):
    with TestClient(service.app) as client:
        assert put_review(client, signed_off_by=name).status_code == 422


def test_review_404_without_a_deck_and_400_for_a_bad_id(service_env):
    with TestClient(service.app) as client:
        assert client.get(f"/proposal/{TENDER_ID}/review", headers=TOKEN).status_code == 404
        assert put_review(client).status_code == 404
        assert client.get("/proposal/a%20b/review", headers=TOKEN).status_code == 400


def test_the_review_file_is_never_served(service_env_with_deck):
    with TestClient(service.app) as client:
        put_review(client, signed_off_by="Ama")
        r = client.get(f"/proposal/{TENDER_ID}/files/reviews/{TENDER_ID}.json", headers=TOKEN)
    assert r.status_code == 404


def test_a_corrupt_review_file_reads_as_absent_and_is_replaced(service_env_with_deck):
    path = service_env_with_deck / "reviews" / f"{TENDER_ID}.json"
    path.parent.mkdir()
    path.write_text("{not json", encoding="utf-8")
    with TestClient(service.app) as client:
        got = client.get(f"/proposal/{TENDER_ID}/review", headers=TOKEN)
        saved = put_review(client, sections={"team": "work"})
    assert got.status_code == 200 and got.json()["sections"] == {}
    assert saved.status_code == 200
    assert json.loads(path.read_text(encoding="utf-8"))["sections"] == {"team": "work"}
    assert not list(path.parent.glob("*.tmp"))


def test_a_review_never_overwrites_another_tenders_deck(service_env_with_deck):
    other = service.ProposalResult(
        tender_id=f"{TENDER_ID}.review", kind="proposal", deck={}, warnings=[],
        artifacts={}, generated_at=GENERATED_AT)
    other_path = service_env_with_deck / f"{TENDER_ID}.review.json"
    other_path.write_text(other.model_dump_json(), encoding="utf-8")
    with TestClient(service.app) as client:
        put_review(client, sections={"team": "work"})
    assert service.ProposalResult.model_validate_json(other_path.read_text(encoding="utf-8")).tender_id == other.tender_id
    assert (service_env_with_deck / "reviews" / f"{TENDER_ID}.json").is_file()



# --- PUT /proposal/refuse/{tender_id}: the review decision, status column only ---

def refuse(client, tender_id=TENDER_ID):
    return client.put(f"/proposal/refuse/{tender_id}", headers=TOKEN)


def stored_no_bid(**overrides):
    fields = dict(meta=Meta(buyer="Sonede", tender_title="WTP extension", reference="R-1",
                            date="2026-01-01", headline="No bid", subtitle="Gap on every requirement"),
                  requirements=[RequirementRow(requirement="ETL pipelines",
                                               evidence="nothing retrieved", score=0.1)],
                  warnings=["no-bid recommendation: every requirement is a Gap"],
                  recommendation="Do not bid.")
    fields.update(overrides)
    return NoBid(**fields)


def test_refuse_marks_a_stored_proposal_refused(service_env):
    with TestClient(service.app) as client:
        assert client.post(f"/proposal/{TENDER_ID}", json=team_bundle(),
                           headers=TOKEN).status_code == 200
        r = refuse(client)
        deck = client.get(f"/proposal/{TENDER_ID}", headers=TOKEN).json()["deck"]
    assert r.status_code == 200, r.text
    assert r.json() == {"tender_id": TENDER_ID, "kind": "proposal",
                        "review_status": "refused"}
    assert deck["review_status"] == "refused"


def test_refuse_marks_a_stored_no_bid_refused(service_env, monkeypatch):
    # Weak retrieval: compose() returns a NoBid, the deck kind refuse must accept.
    monkeypatch.setattr(service, "_search",
                        lambda client, token, query, top_k, doc_type:
                        [META_PRJ[0] | {"similarity": 0.2}])
    with TestClient(service.app) as client:
        assert client.post(f"/proposal/{TENDER_ID}", json=team_bundle(),
                           headers=TOKEN).status_code == 200
        r = refuse(client)
        deck = client.get(f"/proposal/{TENDER_ID}", headers=TOKEN).json()["deck"]
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "no_bid"
    assert deck["review_status"] == "refused"
    assert deck["recommendation"] == "Do not bid." or deck["recommendation"]


def test_refuse_touches_the_review_status_column_only(service_env):
    with TestClient(service.app) as client:
        # inside the client: its lifespan is what creates the schema
        store.save_deck(TENDER_ID, stored_no_bid(), warnings=["kept warning"],
                        artifacts={"pptx": f"{TENDER_ID}.pptx"}, review_status="draft")
        r = refuse(client)
    row = store.get_deck_by_tender_id(TENDER_ID)
    assert r.status_code == 200
    assert row.review_status == "refused"
    assert row.warnings == ["kept warning"]          # untouched
    assert store.get_deck_artifacts(TENDER_ID) == {"pptx": f"{TENDER_ID}.pptx"}
    assert row.recommendation == "Do not bid."       # deck body untouched


def test_refuse_twice_conflicts(service_env):
    with TestClient(service.app) as client:
        store.save_deck(TENDER_ID, stored_no_bid(), review_status="draft")
        first = refuse(client)
        second = refuse(client)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["message"] == "Proposal already refused"


def test_refuse_404_without_a_deck_and_400_for_a_bad_id(service_env):
    with TestClient(service.app) as client:
        assert refuse(client).status_code == 404
        assert refuse(client, tender_id="a b").status_code == 400
