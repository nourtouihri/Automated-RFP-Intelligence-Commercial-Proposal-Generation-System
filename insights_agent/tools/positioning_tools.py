"""The LLM proposes the pitch; the code validates it and adds the risks later."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from insights_agent.tools.context import AgentContext

Item = Annotated[str, Field(min_length=3, max_length=200)]


class PositioningProposal(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    olivesoft_advantages: list[Item] = Field(default_factory=list, max_length=5)
    differentiators_to_emphasize: list[Item] = Field(default_factory=list, max_length=5)
    recommended_strategy: str = Field(default="", max_length=500)


async def propose_positioning(args: dict, ctx: AgentContext) -> dict:
    try:
        proposal = PositioningProposal.model_validate(args)
    except ValidationError as exc:
        details = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        return {"ok": False, "error": "invalid_positioning", "details": details}

    ctx.positioning_proposal = proposal.model_dump()
    names = sorted({f.name for f in ctx.web_facts if f.category == "competitor" and f.name})
    return {"ok": True, "verified_competitors": names}