"""API: tender lookup, run + save, single-flight, errors. No real LLM, search or database."""

import asyncio
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from insights_agent import adapters, api, store  # noqa: E402
from insights_agent.app import app  # noqa: E402
from shared.auth import require_internal_token  # noqa: E402

TENDER = {
    "id": "tender-001", "title": "Intégration RH", "issuer": "Meridian",
    "raw_text": "Budget estimé : 500 000 TND.",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    folder = tmp_path / "feed"
    folder.mkdir()
    (folder / "tender_001.json").write_text(json.dumps(TENDER), encoding="utf-8")
    monkeypatch.setenv("INSIGHTS_TENDERS_DIR", str(folder))
    monkeypatch.setenv("INSIGHTS_DB_PATH", str(tmp_path / "i.db"))
    monkeypatch.setattr(api, "_from_team_store", lambda tender_id: None)

    replies = []

    async def llm(text, system=None):
        if not replies:
            replies.extend([{"action": "find_explicit_budget"}, {"action": "finish"}])
        return json.dumps(replies.pop(0))

    monkeypatch.setattr(api, "providers", lambda: {
        "llm_call": llm, "web_search": None, "fetch_page": None, "rag_query": None,
    })
    app.dependency_overrides[require_internal_token] = lambda: "test-token"
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_post_runs_the_agent_and_saves(client):
    r = client.post("/insights/tender-001")
    assert r.status_code == 200
    body = r.json()
    assert body["insights"]["budget"]["likely"] == 500_000
    assert body["run_id"] and body["trace"][0]["action"] == "find_explicit_budget"
    assert store.get_run(body["run_id"])["tender_id"] == "tender-001"


def test_file_name_style_id_is_accepted(client):
    assert client.post("/insights/tender_001").status_code == 200


def test_unknown_tender_is_404(client):
    assert client.post("/insights/tender-999").status_code == 404


def test_bad_id_is_rejected(client):
    assert client.post("/insights/bad%20id").status_code == 422


def test_get_returns_latest_saved_run(client):
    assert client.get("/insights/tender-001").status_code == 404
    run_id = client.post("/insights/tender-001").json()["run_id"]
    got = client.get("/insights/tender_001").json()
    assert got["run_id"] == run_id and got["insights"]["tender_id"] == "tender-001"


def test_routes_require_the_internal_token_dependency(client):
    app.dependency_overrides.clear()
    r = TestClient(app).post("/insights/tender-001")
    assert r.status_code in (401, 403, 422, 500)  # rejected, never a 200
    assert r.status_code != 200


def test_concurrent_requests_share_one_run(tmp_path, monkeypatch):
    folder = tmp_path / "feed"
    folder.mkdir()
    (folder / "tender_001.json").write_text(json.dumps(TENDER), encoding="utf-8")
    monkeypatch.setenv("INSIGHTS_TENDERS_DIR", str(folder))
    monkeypatch.setenv("INSIGHTS_DB_PATH", str(tmp_path / "i.db"))
    monkeypatch.setattr(api, "_from_team_store", lambda tender_id: None)

    calls = {"n": 0}

    async def slow_run(tender, **kw):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        raise RuntimeError("stop here")

    monkeypatch.setattr(api, "providers", lambda: {})
    monkeypatch.setattr(api, "run_agent", slow_run)

    async def go():
        results = await asyncio.gather(
            api.create_insights("tender-001"),
            api.create_insights("tender_001"),
            return_exceptions=True,
        )
        return results

    results = asyncio.run(go())
    assert calls["n"] == 1
    assert all(isinstance(r, RuntimeError) for r in results)


# --- adapters ---------------------------------------------------------------


def test_web_adapter_serves_tavily_excerpts_without_downloading():
    class R:
        def __init__(self, url, content):
            self.url, self.content = url, content

    class FakeTool:
        async def search(self, query):
            return [R("https://a.example/1", "attribué à Acme pour 120 000 TND")]

    search, fetch = adapters.make_web_adapters(FakeTool())

    async def go():
        results = await search("portail")
        return results, await fetch("https://a.example/1"), await fetch("https://other")

    results, page, missing = asyncio.run(go())
    assert results[0]["url"] == "https://a.example/1"
    assert "120 000 TND" in page and missing == ""


def test_rag_adapter_extracts_title_and_amount():
    rows = [
        {"content": "Portail citoyen livré pour 90 000 TND.", "source_file": "p1.md", "metadata": {"title": "Portail A"}},
        {"content": "Sans prix.", "source_file": "p2.md", "metadata": {"budget": "110 000 TND"}},
        {"content": "Rien.", "source_file": "p3.md", "metadata": {}},
    ]
    rag = adapters.make_rag_query(lambda q: rows)
    out = asyncio.run(rag("portail"))
    assert out == [
        {"title": "Portail A", "budget_tnd": 90_000.0, "delivered": False},
        {"title": "p2.md", "budget_tnd": 110_000.0, "delivered": False},
        {"title": "p3.md", "budget_tnd": None, "delivered": False},
    ]