"""State shared by the tools during one agent run.

The runner creates one AgentContext per tender. Tools read and write it; the
LLM never touches it directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from insights_agent.budget import Amount
from insights_agent.extractor import VerifiedFact
from insights_agent.schemas import BudgetEstimate, Workload

# web_search(query)  -> [{"url": ..., "title": ..., "snippet": ...}, ...]
WebSearchFn = Callable[[str], Awaitable[list[dict]]]
# fetch_page(url)    -> page text
FetchPageFn = Callable[[str], Awaitable[str]]
# rag_query(query)   -> [{"title": ..., "budget_tnd": ...}, ...]
RagQueryFn = Callable[[str], Awaitable[list[dict]]]


def _flatten(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [f"{k}: {s}" for k, v in value.items() for s in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _flatten(v)]
    return []


@dataclass
class AgentContext:
    tender: dict
    llm_call: Optional[Callable[..., Awaitable[str]]] = None
    web_search: Optional[WebSearchFn] = None
    fetch_page: Optional[FetchPageFn] = None
    rag_query: Optional[RagQueryFn] = None
    daily_rate: Optional[float] = None

    # Filled by the tools.
    explicit: list[Amount] = field(default_factory=list)
    web_facts: list[VerifiedFact] = field(default_factory=list)
    comparable_values_tnd: list[float] = field(default_factory=list)
    comparable_sources: list[str] = field(default_factory=list)
    past_values_tnd: list[float] = field(default_factory=list)
    past_projects: list[dict] = field(default_factory=list)
    visited_urls: set[str] = field(default_factory=set)
    disabled_tools: set[str] = field(default_factory=set)
    workload_floor_rejections: int = 0
    workload: Optional[Workload] = None
    budget: Optional[BudgetEstimate] = None
    positioning_proposal: Optional[dict] = None

    @property
    def tender_id(self) -> str:
        return str(self.tender.get("id") or self.tender.get("tender_id") or "unknown")

    @property
    def tender_title(self) -> str:
        return str(self.tender.get("title") or "")

    @property
    def tender_text(self) -> str:
        return "\n".join(_flatten(self.tender))