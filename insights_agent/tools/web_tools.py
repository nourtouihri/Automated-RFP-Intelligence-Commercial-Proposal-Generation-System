"""Web search. The LLM never sees raw page text: only facts the code verified."""

from __future__ import annotations

import logging
import re

from insights_agent.extractor import extract_insights
from insights_agent.tools.context import AgentContext

logger = logging.getLogger(__name__)

MAX_PAGES_PER_SEARCH = 3
MIN_QUERY_CHARS = 3
MAX_QUERY_CHARS = 200

# An amount that is a salary, a subscription, a licence-inclusive programme cost
# or a unit price is not a project budget.
_BAD_AMOUNT_CONTEXT = re.compile(
    r"/\s*(mo|month|monthly|yr|year|annual|hr|hour|day)\b"
    r"|per[\s-]+(user|seat|month|year|hour|day|developer|entity|country|employee)"
    r"|\b(salary|salaries|wage|hourly|subscription|licen[cs]e fee|setup fee|implementation fee"
    r"|annual (program|programme|cost|spend)|including licen[cs]\w+)\b",
    re.IGNORECASE,
)
# Pages that talk about a vendor's customers, not about its competitors.
_NOT_COMPETITOR_URL = ("/case-stud", "/customers", "/customer-stories", "/success-stories")

# Software vendors sell the product the tender asks to integrate: they do not bid
# for the integration work. Not exhaustive: the service-marker rule below is the main filter.
_SOFTWARE_VENDORS = frozenset({
    "salesforce", "workday", "sap", "successfactors", "oracle", "microsoft", "adp",
    "ukg", "bamboohr", "gloroots", "deel", "rippling", "remote", "oyster", "papaya global",
    "mulesoft", "boomi", "informatica", "snaplogic", "workato", "zapier", "servicenow",
})
# A competitor must be presented by its source as a services company (integrator, consultancy...).
_SERVICE_MARKER = re.compile(
    r"\b(consult\w*|integrators?|system integrators?|implementation (partner|firm|services?)"
    r"|it services|managed services|services (firm|provider|company)|digital agency"
    r"|esn|systems? integration (firm|partner|specialist)"
    r"|attribu\w+|adjug\w+|remport\w+|retenu\w*|lauréat"
    r"|awarded|won the (contract|tender|bid)|selected (by|for)|winning bidder)\b",
    re.IGNORECASE,
)


def is_valid_comparable(value: str) -> bool:
    """False for salaries, monthly licences and other amounts that are not a project price."""
    return not _BAD_AMOUNT_CONTEXT.search(value or "")


def is_valid_competitor(
    name: str | None, url: str, tender_text: str, evidence: str | None = None
) -> bool:
    """Keep only plausible bidders for the integration work.

    False for: the platform the tender asks for, customers quoted in case studies,
    known software vendors, and (when the source sentence is given) any company
    that the sentence does not present as a services firm.
    """
    if not name:
        return True
    if name.casefold() in tender_text.casefold():
        return False
    if any(marker in url.lower() for marker in _NOT_COMPETITOR_URL):
        return False
    if name.strip().casefold() in _SOFTWARE_VENDORS:
        return False
    if evidence is not None and not _SERVICE_MARKER.search(evidence):
        return False
    return True


async def search_web(args: dict, ctx: AgentContext) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not (MIN_QUERY_CHARS <= len(query.strip()) <= MAX_QUERY_CHARS):
        return {"ok": False, "error": "invalid_query"}
    if ctx.web_search is None or ctx.fetch_page is None:
        return {"ok": False, "error": "search_unavailable"}

    try:
        results = await ctx.web_search(query.strip())
    except Exception:
        logger.warning("web search failed", exc_info=True)
        return {"ok": False, "error": "search_failed"}

    comparable_out: list[dict] = []
    competitor_out: list[dict] = []
    rejected = 0
    pages_read = 0
    tender_text = ctx.tender_text

    for item in results or []:
        if pages_read >= MAX_PAGES_PER_SEARCH:
            break
        url = item.get("url") if isinstance(item, dict) else None
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        if url in ctx.visited_urls:
            continue
        ctx.visited_urls.add(url)

        try:
            page = await ctx.fetch_page(url)
        except Exception:
            logger.warning("page fetch failed: %s", url, exc_info=True)
            continue
        pages_read += 1

        extraction = await extract_insights(
            page, url, ctx.llm_call, tender_title=ctx.tender_title
        )
        rejected += len(extraction.rejected)

        for fact in extraction.facts:
            if fact.category == "comparable_budget":
                if not is_valid_comparable(fact.value):
                    rejected += 1
                    continue
                ctx.web_facts.append(fact)
                # One value per fact, so a sentence with two amounts is not counted twice.
                ctx.comparable_values_tnd.append(fact.amounts_tnd[0])
                ctx.comparable_sources.append(fact.source_url)
                comparable_out.append(
                    {"value": fact.value, "amount_tnd": fact.amounts_tnd[0], "url": url}
                )
            else:
                if not is_valid_competitor(fact.name, url, tender_text, evidence=fact.value):
                    rejected += 1
                    continue
                ctx.web_facts.append(fact)
                competitor_out.append({"name": fact.name, "category": fact.category,
                                       "evidence": fact.value, "url": url})
    return {
        "ok": True,
        "pages_read": pages_read,
        "comparable_budgets": comparable_out,
        "competitors": competitor_out,
        "rejected_unverified": rejected,
    }