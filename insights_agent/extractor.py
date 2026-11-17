"""Quarantined extractor: the LLM copies spans, the code verifies them.

Nothing the model returns is trusted:
- the JSON must match InsightExtractorOutput (strict, unknown keys rejected);
- every span must be found in the page text;
- amounts are re-parsed by budget.parse_amounts, never read from the model;
- the source URL is the one the runner passed in, never one from the model.

Same contract as research/extractor.py: trusted instructions via system=,
untrusted page via the user message, fail closed, drift is logged.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from pydantic import ValidationError
from insights_agent.llm import default_llm_call 
from insights_agent.budget import (
    MAX_PLAUSIBLE_TND,
    MIN_PLAUSIBLE_TND,
    fold_text,
    parse_amounts,
)
from insights_agent.prompts import (
    EXTRACTOR_SYSTEM,
    SNIPPET_CAP_CHARS,
    build_user_message,
)
from insights_agent.schemas import InsightExtractorOutput
from shared.redaction import SecretScrubber

logger = logging.getLogger(__name__)

# On the logger, not a handler, so records are scrubbed before any handler sees them.
if not any(isinstance(f, SecretScrubber) for f in logger.filters):
    logger.addFilter(SecretScrubber())

# One page cannot plausibly support more than a handful of facts.
FACT_CAP = 8
_REPLY_LOG_CHARS = 200

# Names that can never be a competitor.
OWN_NAMES = ("olivesoft", "olive soft")

# detection.llm.llm_call: async, llm_call(text, system=...) -> str
LlmCall = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class VerifiedFact:
    category: str                    # "comparable_budget" | "competitor"
    value: str                       # verbatim span, checked against the page
    name: Optional[str]              # competitor name, checked against the page
    amounts_tnd: tuple[float, ...]   # re-parsed by the code (comparable_budget only)
    confidence: str
    source_url: str                  # attached by the code


@dataclass
class ExtractionResult:
    facts: list[VerifiedFact] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)   # {"reason": ..., "value": ...}
    # llm_call_failed | empty_reply | invalid_json | schema_drift | bad_url | empty_page
    error: Optional[str] = None


def _log_reply(reason: str, raw: str) -> None:
    logger.warning(
        "Insights extractor contract violation (%s); reply was: %r",
        reason,
        raw[:_REPLY_LOG_CHARS],
    )


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()


def _normalize(text: str) -> str:
    """Folded, whitespace-collapsed text: used only to compare, never to output."""
    return re.sub(r"\s+", " ", fold_text(text)).strip()


async def extract_insights(
    page_text: str,
    source_url: str,
    llm_call: Optional[LlmCall] = None,
    *,
    tender_title: str = "",
) -> ExtractionResult:
    """Read one page. Returns only facts the code could verify."""
    result = ExtractionResult()

    if not source_url.startswith(("http://", "https://")):
        result.error = "bad_url"
        return result
    if not page_text or not page_text.strip():
        result.error = "empty_page"
        return result

    if llm_call is None:
        from insights_agent.llm import default_llm_call  # lazy: easy to fake in tests
        llm_call = default_llm_call

    page = page_text[:SNIPPET_CAP_CHARS]

    try:
        raw = (await llm_call(build_user_message(page, tender_title),
                              system=EXTRACTOR_SYSTEM)).strip()
    except Exception:
        # Transport/auth/timeout: never crash the agent.
        logger.warning("Insights extractor LLM call failed", exc_info=True)
        result.error = "llm_call_failed"
        return result

    cleaned = _strip_fences(raw) if raw else ""
    if not cleaned or cleaned.lower() == "null":
        result.error = "empty_reply"
        return result

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        _log_reply("not valid JSON", raw)
        result.error = "invalid_json"
        return result

    if not isinstance(data, dict):
        _log_reply(f"top-level {type(data).__name__}, expected object", raw)
        result.error = "invalid_json"
        return result

    try:
        parsed = InsightExtractorOutput.model_validate(data)
    except ValidationError as exc:
        extra = sorted(
            {str(e["loc"][0]) for e in exc.errors()
             if e["type"] == "extra_forbidden" and e["loc"]}
        )
        if extra:
            logger.warning(
                "Insights extractor reply carried forbidden extra key(s) %s; "
                "facts discarded (fail-closed)", extra,
            )
        else:
            _log_reply("schema mismatch", raw)
        result.error = "schema_drift"
        return result

    facts = parsed.facts
    if len(facts) > FACT_CAP:
        logger.info("Insights extractor returned %d facts; capping at %d", len(facts), FACT_CAP)
        facts = facts[:FACT_CAP]

    page_norm = _normalize(page)
    seen: set[tuple[str, str]] = set()

    for fact in facts:
        key = (fact.category, _normalize(fact.value))
        if key in seen:
            continue
        seen.add(key)

        if _normalize(fact.value) not in page_norm:
            result.rejected.append({"reason": "value_not_in_page", "value": fact.value})
            continue

        if fact.category == "comparable_budget":
            amounts = [
                a.value_tnd for a in parse_amounts(fact.value)
                if MIN_PLAUSIBLE_TND <= a.value_tnd <= MAX_PLAUSIBLE_TND
            ]
            if not amounts:
                result.rejected.append({"reason": "no_plausible_amount", "value": fact.value})
                continue
            result.facts.append(VerifiedFact(
                category=fact.category, value=fact.value, name=None,
                amounts_tnd=tuple(amounts), confidence=fact.confidence,
                source_url=source_url,
            ))
            continue

        # competitor
        name_norm = _normalize(fact.name or "")
        if any(own in name_norm for own in OWN_NAMES):
            result.rejected.append({"reason": "own_company", "value": fact.value})
            continue
        if not name_norm or name_norm not in page_norm:
            result.rejected.append({"reason": "name_not_in_page", "value": fact.value})
            continue
        result.facts.append(VerifiedFact(
            category=fact.category, value=fact.value, name=fact.name,
            amounts_tnd=(), confidence=fact.confidence, source_url=source_url,
        ))

    return result