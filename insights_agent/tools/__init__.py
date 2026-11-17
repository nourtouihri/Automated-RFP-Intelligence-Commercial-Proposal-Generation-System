"""The tools the agent can choose from. `finish` belongs to the runner."""

from __future__ import annotations

import logging

from insights_agent.tools.budget_tools import compute_budget, propose_workload
from insights_agent.tools.context import AgentContext
from insights_agent.tools.positioning_tools import propose_positioning
from insights_agent.tools.rag_tools import search_past_projects
from insights_agent.tools.tender_tools import find_explicit_budget, read_tender
from insights_agent.tools.web_tools import search_web

logger = logging.getLogger(__name__)

TOOLS = {
    "read_tender": read_tender,
    "find_explicit_budget": find_explicit_budget,
    "search_web": search_web,
    "search_past_projects": search_past_projects,
    "propose_workload": propose_workload,
    "propose_positioning": propose_positioning,
    "compute_budget": compute_budget,
}

ALLOWED_ACTIONS = frozenset(TOOLS) | {"finish"}

# An outage-type error switches the tool off for the rest of the run.
# Errors caused by the model's own arguments (invalid_query, ...) do not.
DISABLING_ERRORS = frozenset({"rag_failed", "search_failed", "tool_crashed"})


def _is_outage(error: str) -> bool:
    return error in DISABLING_ERRORS or error.endswith("_unavailable")


async def run_tool(name: str, args: dict, ctx: AgentContext) -> dict:
    """Run one tool. Never raises: a broken tool becomes an error result.

    After an outage-type failure the tool is disabled for the rest of the run,
    so the agent cannot waste turns calling it again.
    """
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": "unknown_action"}

    if name in ctx.disabled_tools:
        return {
            "ok": False,
            "error": "tool_disabled",
            "hint": f"{name} a deja echoue. Ne le rappelle pas, passe a l'etape suivante.",
        }

    try:
        result = await tool(args, ctx)
    except Exception:
        logger.warning("tool %s crashed", name, exc_info=True)
        ctx.disabled_tools.add(name)
        return {"ok": False, "error": "tool_crashed"}

    if not result.get("ok") and _is_outage(str(result.get("error") or "")):
        ctx.disabled_tools.add(name)
        logger.info("tool %s disabled for this run (%s)", name, result.get("error"))
    return result


__all__ = ["ALLOWED_ACTIONS", "AgentContext", "TOOLS", "run_tool"]