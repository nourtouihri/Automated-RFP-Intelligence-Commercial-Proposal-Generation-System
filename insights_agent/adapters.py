"""Adapters from the team's code (Tavily SearchTool, RAG) to the agent's tool interfaces.

Nothing in the team's code is modified: it is only imported, lazily, so the
agent and its tests run even when a provider is missing or has no credentials.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any, Awaitable, Callable, Optional

from insights_agent.budget import MAX_PLAUSIBLE_TND, MIN_PLAUSIBLE_TND, parse_amounts

logger = logging.getLogger(__name__)

SEARCH_MODULE_CANDIDATES = ("research.search", "research.search_tool", "research.tools")
_BUDGET_KEYS = ("budget_tnd", "amount_tnd", "budget", "amount", "price", "cost")
_TITLE_KEYS = ("title", "name", "project", "project_name")

# A project counts as proof of past work only if it was really delivered to a client.
_NOT_A_REFERENCE = frozenset({"pfe_internship_project", "internship", "academic", "training"})
_DELIVERED_OUTCOMES = frozenset({"delivered", "completed", "live", "in_production", "won"})


def _load_search_tool() -> Any | None:
    for module_name in SEARCH_MODULE_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        tool_cls = getattr(module, "SearchTool", None)
        if tool_cls is not None:
            return tool_cls()
    logger.warning("SearchTool not found in %s: web search disabled", SEARCH_MODULE_CANDIDATES)
    return None


def make_web_adapters(search_tool: Any | None = None):
    """Returns (web_search, fetch_page), or (None, None) when no provider exists.

    Tavily already returns a cleaned excerpt per result, so fetch_page serves
    that excerpt from memory instead of downloading the page again.
    """
    tool = search_tool if search_tool is not None else _load_search_tool()
    if tool is None:
        return None, None

    excerpts: dict[str, str] = {}

    async def web_search(query: str) -> list[dict]:
        results = await tool.search(query)
        out = []
        for r in results or []:
            excerpts[r.url] = r.content
            out.append({"url": r.url, "title": "", "snippet": r.content[:200]})
        return out

    async def fetch_page(url: str) -> str:
        return excerpts.get(url, "")

    return web_search, fetch_page


def _project_amount(metadata: dict, content: str) -> float | None:
    for key in _BUDGET_KEYS:
        value = metadata.get(key)
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
    for amount in parse_amounts(content):
        if MIN_PLAUSIBLE_TND <= amount.value_tnd <= MAX_PLAUSIBLE_TND:
            return amount.value_tnd
    return None


def _project_title(metadata: dict, source_file: str) -> str:
    """Readable title: explicit title if any, else record id | domain | main technologies."""
    for key in _TITLE_KEYS:
        if metadata.get(key):
            return str(metadata[key])
    rid = str(metadata.get("record_id") or "").strip()
    domain = metadata.get("domain")
    domain_txt = "/".join(str(d) for d in domain) if isinstance(domain, list) else str(domain or "")
    stack = metadata.get("tech_stack")
    stack_txt = ", ".join(str(s) for s in stack[:3]) if isinstance(stack, list) else ""
    parts = [p for p in (rid, domain_txt, stack_txt) if p]
    return " | ".join(parts) if parts else (source_file or "projet")


def _is_delivered(metadata: dict) -> bool:
    """True only for a real delivered project. Missing information means False."""
    relationship = str(metadata.get("relationship") or "").strip().casefold()
    outcome = str(metadata.get("outcome") or "").strip().casefold()
    if relationship in _NOT_A_REFERENCE:
        return False
    return outcome in _DELIVERED_OUTCOMES


def make_rag_query(query_fn: Optional[Callable[..., list[dict]]] = None) -> Callable[[str], Awaitable[list[dict]]]:
    """Wraps the synchronous rag.query.query_knowledge_base for the async loop."""

    def _default(text: str) -> list[dict]:
        from rag.query import query_knowledge_base  # lazy: needs Supabase credentials

        return query_knowledge_base(text, top_k=5, doc_type="project", similarity_threshold=0.2)

    fn = query_fn or _default

    async def rag_query(query: str) -> list[dict]:
        rows = await asyncio.to_thread(fn, query)
        out = []
        for row in rows or []:
            metadata = row.get("metadata") or {}
            out.append({
                "title": _project_title(metadata, str(row.get("source_file") or "")),
                "budget_tnd": _project_amount(metadata, str(row.get("content") or "")),
                "delivered": _is_delivered(metadata),
            })
        return out

    return rag_query