"""Workload validation and budget resolution."""

from __future__ import annotations

import re

from pydantic import ValidationError

from insights_agent.budget import (
    check_against_reference,
    resolve_budget,
    total_person_days,
    weighted_days,
    workload_to_budget,
)
from insights_agent.schemas import Workload
from insights_agent.tools.context import AgentContext

# Fewer comparables than this say nothing reliable about the price.
MIN_COMPARABLES = 3

# Minimum raw working days per country when the tender names a number of countries.
# Adjust with the team: it is a sanity floor, not an estimate.
DAYS_PER_COUNTRY = 12
MAX_FLOOR_COUNTRIES = 30
_COUNTRIES_RE = re.compile(r"\b(\d{1,2})\s+(?:countries|country|pays)\b", re.IGNORECASE)


def detect_country_count(text: str) -> int | None:
    counts = [int(c) for c in _COUNTRIES_RE.findall(text or "")]
    counts = [c for c in counts if 2 <= c <= MAX_FLOOR_COUNTRIES]
    return max(counts) if counts else None


def minimum_days(ctx: AgentContext) -> float | None:
    n = detect_country_count(ctx.tender_text)
    return float(n * DAYS_PER_COUNTRY) if n else None


def _usable_comparables(ctx: AgentContext) -> tuple[list[float], list[str]]:
    if len(ctx.comparable_values_tnd) < MIN_COMPARABLES:
        return [], []
    return ctx.comparable_values_tnd, ctx.comparable_sources


async def propose_workload(args: dict, ctx: AgentContext) -> dict:
    try:
        workload = Workload.model_validate({"tasks": args.get("tasks")})
    except ValidationError as exc:
        details = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        ]
        return {"ok": False, "error": "invalid_workload", "details": details}

    total = total_person_days(workload)
    floor = minimum_days(ctx)
    below_floor = floor is not None and total < floor
    if below_floor and ctx.workload_floor_rejections == 0:
        ctx.workload_floor_rejections += 1
        n = detect_country_count(ctx.tender_text)
        return {
            "ok": False,
            "error": "workload_too_low",
            "details": [
                f"Total {total:g} days is below the minimum {floor:g} days "
                f"for {n} countries ({DAYS_PER_COUNTRY} days per country). "
                "Revise: add per-country configuration, testing and cut-over effort."
            ],
        }

    ctx.workload = workload
    estimate = workload_to_budget(workload, ctx.daily_rate)
    comparables, _ = _usable_comparables(ctx)
    verdict = check_against_reference(
        estimate.likely or 0.0, ctx.past_values_tnd + comparables
    )
    result = {
        "ok": True,
        "total_days": total,
        "weighted_days": weighted_days(workload),
        "effort_likely_tnd": estimate.likely,
        "reference_check": verdict,
    }
    if below_floor:
        result["warning"] = f"Total is below the expected minimum of {floor:g} days."
    return result


async def compute_budget(args: dict, ctx: AgentContext) -> dict:
    comparables, sources = _usable_comparables(ctx)
    ctx.budget = resolve_budget(
        explicit=ctx.explicit,
        comparable_values_tnd=comparables,
        comparable_sources=sources,
        person_days=weighted_days(ctx.workload) if ctx.workload else None,
        daily_rate=ctx.daily_rate,
        tender_source=f"tender:{ctx.tender_id}",
    )
    return {"ok": True, "budget": ctx.budget.model_dump()}