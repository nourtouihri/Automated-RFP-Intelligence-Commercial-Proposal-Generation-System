"""The store keeps every run, returns the latest, and never needs the main database."""

import asyncio
import json

from insights_agent import store
from insights_agent.prompts import EXTRACTOR_SYSTEM
from insights_agent.runner import run_agent

TENDER = {
    "id": "t1", "title": "Refonte portail", "issuer": "Mairie",
    "description": "Budget estimé : 500 000 TND.",
}


def make_run(tender=TENDER):
    replies = [{"action": "find_explicit_budget"}, {"action": "finish"}]

    async def llm(text, system=None):
        if system == EXTRACTOR_SYSTEM:
            return json.dumps({"facts": []})
        return json.dumps(replies.pop(0))

    return asyncio.run(run_agent(tender, llm_call=llm))


def test_save_and_read_back(tmp_path):
    db = tmp_path / "i.db"
    run_id = store.save_run(make_run(), db)
    row = store.get_run(run_id, db)
    assert row["tender_id"] == "t1" and row["method"] == "explicit"
    assert row["insights"]["budget"]["likely"] == 500_000
    assert row["stop_reason"] == "finished"


def test_trace_is_preserved(tmp_path):
    db = tmp_path / "i.db"
    run_id = store.save_run(make_run(), db)
    trace = store.get_run(run_id, db)["trace"]
    assert [s["action"] for s in trace[:2]] == ["find_explicit_budget", "finish"]


def test_latest_returns_the_most_recent_run(tmp_path):
    db = tmp_path / "i.db"
    first = store.save_run(make_run(), db)
    second = store.save_run(make_run(), db)
    assert second > first
    assert store.latest_run("t1", db)["run_id"] == second


def test_unknown_tender_returns_none(tmp_path):
    assert store.latest_run("nope", tmp_path / "i.db") is None
    assert store.get_run(999, tmp_path / "i.db") is None


def test_list_runs_filters_and_limits(tmp_path):
    db = tmp_path / "i.db"
    for _ in range(3):
        store.save_run(make_run(), db)
    store.save_run(make_run({**TENDER, "id": "t2"}), db)
    assert len(store.list_runs("t1", path=db)) == 3
    assert len(store.list_runs(path=db, limit=2)) == 2
    assert "trace" not in store.list_runs("t1", path=db)[0]


def test_missing_folder_is_created(tmp_path):
    db = tmp_path / "a" / "b" / "i.db"
    store.save_run(make_run(), db)
    assert db.exists()


def test_path_can_come_from_the_environment(tmp_path, monkeypatch):
    db = tmp_path / "env.db"
    monkeypatch.setenv("INSIGHTS_DB_PATH", str(db))
    store.save_run(make_run())
    assert db.exists() and store.latest_run("t1")["tender_id"] == "t1"