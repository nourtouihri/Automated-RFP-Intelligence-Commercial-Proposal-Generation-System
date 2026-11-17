"""Past OliveSoft projects, used as a price reference."""

from __future__ import annotations

import logging
import statistics

from insights_agent.budget import MAX_PLAUSIBLE_TND, MIN_PLAUSIBLE_TND, parse_amounts
from insights_agent.tools.context import AgentContext

logger = logging.getLogger(__name__)

MAX_PROJECTS = 5
_AMOUNT_KEYS = ("budget_tnd", "amount_tnd", "budget", "amount")
_TITLE_KEYS = ("title", "name", "project")


def _amount_tnd(project: dict) -> float | None:
    for key in _AMOUNT_KEYS:
        value = project.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            candidate = float(value)
        elif isinstance(value, str):
            parsed = parse_amounts(value)
            if not parsed:
                continue
            candidate = parsed[0].value_tnd
        else:
            continue
        if MIN_PLAUSIBLE_TND <= candidate <= MAX_PLAUSIBLE_TND:
            return candidate
    return None


def _title(project: dict) -> str:
    for key in _TITLE_KEYS:
        value = project.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return "projet sans titre"


async def search_past_projects(args: dict, ctx: AgentContext) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or len(query.strip()) < 3:
        return {"ok": False, "error": "invalid_query"}
    if ctx.rag_query is None:
        return {"ok": False, "error": "rag_unavailable"}

    try:
        rows = await ctx.rag_query(query.strip())
    except Exception:
        logger.warning("RAG query failed", exc_info=True)
        return {"ok": False, "error": "rag_failed"}

    projects: list[dict] = []
    for row in (rows or [])[:MAX_PROJECTS]:
        if not isinstance(row, dict):
            continue
        amount = _amount_tnd(row)
        delivered = row.get("delivered") is True
        projects.append({"title": _title(row), "amount_tnd": amount, "delivered": delivered})
        if amount is not None:
            ctx.past_values_tnd.append(amount)

    ctx.past_projects.extend(projects)
    amounts = [p["amount_tnd"] for p in projects if p["amount_tnd"] is not None]
    return {
        "ok": True,
        "projects": projects,
        "reference_median_tnd": round(statistics.median(amounts)) if amounts else None,
    }