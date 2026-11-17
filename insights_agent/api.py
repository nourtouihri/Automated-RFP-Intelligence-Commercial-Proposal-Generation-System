"""HTTP API of the insights agent.

Same contract as the research service: every route requires X-Internal-Token,
errors use the shared envelope, and concurrent runs on one tender are merged.

POST /insights/{tender_id}  runs the agent, saves the run, returns sheet + trace.
GET  /insights/{tender_id}  returns the latest saved run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from insights_agent import store
from insights_agent.adapters import make_rag_query, make_web_adapters
from insights_agent.runner import run_agent
from shared.auth import require_internal_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/insights",
    tags=["insights"],
    dependencies=[Depends(require_internal_token)],
)

DEFAULT_TENDERS_DIR = Path(__file__).resolve().parents[1] / "detection" / "data" / "simulated_feed"
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")

# Single-flight guard: concurrent requests for one tender share one run.
_running: dict[str, asyncio.Task] = {}


def tenders_dir() -> Path:
    env = os.environ.get("INSIGHTS_TENDERS_DIR")
    return Path(env) if env else DEFAULT_TENDERS_DIR


def _norm(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _from_team_store(tender_id: str) -> Optional[dict]:
    """The team's stored tenders, if shared.store exposes get_tender."""
    try:
        from shared import store as shared_store

        getter = getattr(shared_store, "get_tender", None)
        if getter is None:
            return None
        found = getter(tender_id)
        if found is None:
            return None
        if hasattr(found, "model_dump"):
            found = found.model_dump(mode="json")
        return found if isinstance(found, dict) else None
    except Exception:
        logger.debug("shared.store lookup failed", exc_info=True)
        return None


def _from_feed_folder(tender_id: str) -> Optional[dict]:
    wanted = _norm(tender_id)
    folder = tenders_dir()
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and wanted in (_norm(path.stem), _norm(str(data.get("id", "")))):
            return data
    return None


def load_tender(tender_id: str) -> Optional[dict]:
    """Team store first, then the simulated feed (tender-001 == tender_001)."""
    return _from_team_store(tender_id) or _from_feed_folder(tender_id)


def providers() -> dict:
    """Real providers. Tests replace this function."""
    web_search, fetch_page = make_web_adapters()
    return {
        "llm_call": None,  # None -> the team's detection.llm.llm_call
        "web_search": web_search,
        "fetch_page": fetch_page,
        "rag_query": make_rag_query(),
    }


def _check_id(tender_id: str) -> None:
    if not _ID_RE.match(tender_id):
        raise HTTPException(status_code=422, detail="invalid tender id")


async def _run_and_save(tender: dict) -> dict:
    run = await run_agent(tender, **providers())
    try:
        run_id = await asyncio.to_thread(store.save_run, run)
    except Exception:
        logger.warning("could not save run", exc_info=True)
        run_id = None
    return {
        "run_id": run_id,
        "stop_reason": run.stop_reason,
        "insights": run.insights.model_dump(mode="json"),
        "trace": run.trace,
    }


@router.post("/{tender_id}")
async def create_insights(tender_id: str) -> dict:
    """Runs the agent. POST because a run spends LLM and search budget."""
    _check_id(tender_id)
    tender = load_tender(tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    key = _norm(tender_id)
    task = _running.get(key)
    if task is None:
        task = asyncio.create_task(_run_and_save(tender))
        _running[key] = task
        task.add_done_callback(lambda _t, k=key: _running.pop(k, None))
    # shield: one client disconnecting must not cancel the run the others share.
    return await asyncio.shield(task)


@router.get("/{tender_id}")
async def latest_insights(tender_id: str) -> dict:
    _check_id(tender_id)
    tender = load_tender(tender_id)
    stored_id = str(tender.get("id")) if tender and tender.get("id") else tender_id
    row = await asyncio.to_thread(store.latest_run, stored_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No insights found for tender")
    return row