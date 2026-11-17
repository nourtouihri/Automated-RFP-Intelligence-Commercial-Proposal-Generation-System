"""API contract tests: paid runs are POST-only; finalize persists exactly once."""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

from research.tests.test_runner import make_tender  # noqa: F401  (reuse helper)
from research.search import SearchTool
from shared import store


@pytest.fixture(autouse=True)
def no_network_search(monkeypatch):
    # Hermetic: never hit Tavily/LLM from API tests regardless of ambient keys.
    monkeypatch.setattr(SearchTool, "search", AsyncMock(return_value=[]))


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.init_db()
    from research.tests.test_runner import make_tender as _make

    store.save_tender(_make(), "seed-hash-t1")
    yield


TOKEN_HEADER = {"X-Internal-Token": "test-token"}


@pytest.mark.asyncio
async def test_run_is_post_only_and_persists(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from research.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # The old paid-GET route is gone.
        resp = await client.get("/research/run", params={"tender_id": "t1"}, headers=TOKEN_HEADER)
        assert resp.status_code in (404, 405)

        # POST runs the pipeline and persists exactly once.
        resp = await client.post("/research/t1", headers=TOKEN_HEADER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["tender_id"] == "t1"
        assert body["issuer"] == "MetroDOT"

        # Stored result is retrievable via GET (safe, read-only).
        resp = await client.get("/research/t1", headers=TOKEN_HEADER)
        assert resp.status_code == 200
        assert resp.json()["tender_id"] == "t1"


@pytest.mark.asyncio
async def test_run_missing_tender_is_404():
    from research.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/research/does-not-exist", headers=TOKEN_HEADER)
        assert resp.status_code == 404


def _research(tender_id="t1", issuer="MetroDOT", sector="Transport"):
    from shared.schemas import ProspectResearch

    return ProspectResearch(
        tender_id=tender_id,
        issuer=issuer,
        sector=sector,
        estimated_revenue=None,
        past_projects=[],
        key_partners=[],
        notes="",
        confidence="low",
        sources=[],
    )


def test_get_research_by_tender_id_binds_single_parameter():
    """Regression: the binding must be a 1-tuple, not a bare string.

    `(tender_id)` is not a tuple — sqlite3 would bind it as a sequence of
    individual characters and raise "Incorrect number of bindings supplied"
    for any id longer than one character. Dormant while nothing called it,
    fatal the moment runner.py's `TODO: change to get_research_by_tenderid`
    is picked up.
    """
    store.save_research("t1", _research("t1"))
    found = store.get_research_by_tender_id("t1")
    assert found is not None
    assert found.tender_id == "t1"
    assert store.get_research_by_tender_id("does-not-exist") is None


def test_get_research_by_issuer_returns_most_recent_not_lexicographic():
    """Regression: recency must not be `ORDER BY tender_id`.

    tender_id is an opaque string, so lexicographic order puts "t1" before
    "t10" and "t2" — i.e. the cache would serve stale research for a
    re-researched issuer. rowid is the insertion counter, so
    ORDER BY rowid DESC is true recency. These ids are chosen so the newest
    ("t10") is NOT the lexicographically smallest ("t1"): a lexicographic
    lookup returns the stale first result and fails this assertion.
    """
    from research.tests.test_runner import make_tender as _make

    for tid in ("t2", "t10"):
        t = _make()
        t.id = tid
        store.save_tender(t, f"hash-{tid}")

    # Oldest -> newest. "t1" is the oldest and is also the lexicographically
    # smallest, so a lexicographic lookup returns stale "t1" and fails.
    for tid, sector in (("t1", "oldest"), ("t2", "second"), ("t10", "newest")):
        store.save_research(tid, _research(tid, sector=sector))

    latest = store.get_research_by_issuer("MetroDOT")
    assert latest is not None
    assert latest.tender_id == "t10"
    assert latest.sector == "newest"


@pytest.mark.asyncio
async def test_audit_route_returns_the_latest_run(tmp_path, monkeypatch):
    from research import runner
    from research.main import app
    from research.tests.test_audit_reader import search, start, write_log

    log = write_log(tmp_path, [start("t1", "run_a"), search("run_a"), start("t1", "run_b"), search("run_b", "hit")])
    monkeypatch.setattr(runner, "LOG_PATH", str(log))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/research/t1/audit", headers=TOKEN_HEADER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "run_b"
        assert [e["tool"] for e in body["entries"]] == ["research_run_start", "search"]
        assert body["entries"][-1]["content"] == "hit"

        none = await client.get("/research/t9/audit", headers=TOKEN_HEADER)
        assert none.json() == {"run_id": None, "entries": []}

        unauth = await client.get("/research/t1/audit")
        assert unauth.status_code in (401, 403)


@pytest.mark.asyncio
async def test_a_tender_id_with_slashes_is_reachable_for_run_get_and_audit(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from research import runner
    from research.main import app
    from research.tests.test_audit_reader import search, start, write_log

    tender = make_tender().model_copy(update={"id": "Lot 3 / North"})
    store.save_tender(tender, "seed-hash-slash")
    log = write_log(tmp_path, [start("Lot 3 / North", "run_a"), search("run_a")])
    monkeypatch.setattr(runner, "LOG_PATH", str(log))
    quoted = "Lot%203%20%2F%20North"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ran = await client.post(f"/research/{quoted}", headers=TOKEN_HEADER)
        assert ran.status_code == 200 and ran.json()["tender_id"] == "Lot 3 / North"

        got = await client.get(f"/research/{quoted}", headers=TOKEN_HEADER)
        assert got.status_code == 200 and got.json()["tender_id"] == "Lot 3 / North"

        audit = await client.get(f"/research/{quoted}/audit", headers=TOKEN_HEADER)
        assert audit.status_code == 200 and audit.json()["run_id"] and audit.json()["entries"]

        listed = await client.get("/research", headers=TOKEN_HEADER)
        assert "Lot 3 / North" in listed.json()
