"""Tools that read the tender itself."""

from __future__ import annotations

from insights_agent.budget import find_explicit_budget as _find_explicit_budget
from insights_agent.tools.context import AgentContext

TENDER_TEXT_CAP = 6_000


async def read_tender(args: dict, ctx: AgentContext) -> dict:
    text = ctx.tender_text
    return {
        "ok": True,
        "tender_id": ctx.tender_id,
        "title": ctx.tender_title,
        "text": text[:TENDER_TEXT_CAP],
        "truncated": len(text) > TENDER_TEXT_CAP,
    }


async def find_explicit_budget(args: dict, ctx: AgentContext) -> dict:
    found = _find_explicit_budget(ctx.tender_text)
    ctx.explicit = found
    return {
        "ok": True,
        "found": bool(found),
        "amounts": [
            {"raw": a.raw, "currency": a.currency, "value_tnd": a.value_tnd} for a in found
        ],
    }