"""The agent's own small database (SQLite). Nothing else in the repo is touched.

One row per run: the full insights sheet, the trace and the stop reason, so a
past analysis can be shown again ("here is what the agent did and why").
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "insights.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    status        TEXT,
    confidence    TEXT,
    method        TEXT,
    stop_reason   TEXT,
    insights_json TEXT NOT NULL,
    trace_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_tender ON runs (tender_id, id);
"""


def db_path(path: Optional[str | Path] = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("INSIGHTS_DB_PATH")
    return Path(env) if env else DEFAULT_DB_PATH


def _connect(path: Optional[str | Path] = None) -> sqlite3.Connection:
    p = db_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["id"],
        "tender_id": row["tender_id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "confidence": row["confidence"],
        "method": row["method"],
        "stop_reason": row["stop_reason"],
        "insights": json.loads(row["insights_json"]),
        "trace": json.loads(row["trace_json"]),
    }


def save_run(run, path: Optional[str | Path] = None) -> int:
    """Save one AgentRun. Returns the new run id."""
    insights = run.insights
    payload = insights.model_dump(mode="json")
    created = payload.get("completed_at") or ""
    with closing(_connect(path)) as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO runs (tender_id, created_at, status, confidence, method, "
                "stop_reason, insights_json, trace_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    insights.tender_id,
                    created,
                    insights.status,
                    insights.confidence,
                    insights.budget.method,
                    run.stop_reason,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(run.trace, ensure_ascii=False, default=str),
                ),
            )
        return int(cur.lastrowid)


def get_run(run_id: int, path: Optional[str | Path] = None) -> Optional[dict]:
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _row_to_dict(row) if row else None


def latest_run(tender_id: str, path: Optional[str | Path] = None) -> Optional[dict]:
    with closing(_connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE tender_id = ? ORDER BY id DESC LIMIT 1", (tender_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_runs(
    tender_id: Optional[str] = None, limit: int = 20, path: Optional[str | Path] = None
) -> list[dict]:
    """Most recent first, without the heavy trace (summary rows only)."""
    limit = max(1, min(int(limit), 100))
    query = "SELECT id, tender_id, created_at, status, confidence, method, stop_reason FROM runs"
    params: tuple = ()
    if tender_id:
        query += " WHERE tender_id = ?"
        params = (tender_id,)
    query += " ORDER BY id DESC LIMIT ?"
    with closing(_connect(path)) as conn:
        rows = conn.execute(query, params + (limit,)).fetchall()
    return [
        {
            "run_id": r["id"], "tender_id": r["tender_id"], "created_at": r["created_at"],
            "status": r["status"], "confidence": r["confidence"],
            "method": r["method"], "stop_reason": r["stop_reason"],
        }
        for r in rows
    ]