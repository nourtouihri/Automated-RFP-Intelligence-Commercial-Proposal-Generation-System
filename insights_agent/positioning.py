"""Positioning: the LLM proposes the pitch, the code computes the risks.

Risks are never written by the model. They come from the evidence gathered
(or the lack of it), so each one can be traced to a number or a missing source.

OliveSoft advantages are claims about OliveSoft's past work. The model may only
keep them when at least one delivered project was found in the RAG.
"""

from __future__ import annotations

from insights_agent.budget import (
    EFFORT_MIN_FACTOR,
    check_against_reference,
    workload_to_budget,
)
from insights_agent.schemas import COMPETITOR_CATEGORIES, Positioning
from insights_agent.tools.context import AgentContext

# Same rule as compute_budget: fewer comparables say nothing reliable about a price.
MIN_COMPARABLES = 3


def delivered_projects(ctx: AgentContext) -> list[dict]:
    """Past projects the adapter marked as really delivered (not internships or proposals)."""
    return [p for p in ctx.past_projects if isinstance(p, dict) and p.get("delivered") is True]


def _usable_comparables(ctx: AgentContext) -> list[float]:
    if len(ctx.comparable_values_tnd) < MIN_COMPARABLES:
        return []
    return list(ctx.comparable_values_tnd)


def compute_risks(ctx: AgentContext) -> list[str]:
    risks: list[str] = []
    budget = ctx.budget

    verified = {f.name.casefold() for f in ctx.web_facts
                if f.category in COMPETITOR_CATEGORIES and f.name}
    if not verified:
        risks.append(
            "Aucun concurrent vérifié : l'analyse concurrentielle est vide, "
            "ce qui ne prouve pas l'absence de concurrence."
        )

    for f in [f for f in ctx.web_facts if f.category == "competitor_strength" and f.name][:3]:
        risks.append(f"Concurrent {f.name} : point fort cité par la source ({f.source_url}) : {f.value[:150]}")

    if budget is None or budget.method == "none":
        risks.append("Aucun budget n'a pu être estimé : ne pas fixer de prix sans information supplémentaire.")
        return risks

    if budget.confidence == "low":
        risks.append("Confiance faible sur le budget : à valider avec un chiffrage détaillé avant de répondre.")

    effort = workload_to_budget(ctx.workload, ctx.daily_rate).likely if ctx.workload else None
    if effort:
        if budget.method == "explicit" and budget.max is not None and effort * EFFORT_MIN_FACTOR > budget.max:
            risks.append(
                f"Le budget écrit ({budget.max:,.0f} TND) est inférieur à notre estimation d'effort "
                f"({effort:,.0f} TND) : risque de marge négative ou de périmètre à réduire."
            )
        check = check_against_reference(effort, ctx.past_values_tnd + _usable_comparables(ctx))
        if check["suspicious"]:
            risks.append(
                f"Notre estimation d'effort s'écarte fortement des références "
                f"(médiane {check['reference']:,} TND, rapport {check['ratio']}) : périmètre probablement sous-estimé ou sur-estimé."
            )
    return risks


def build_positioning(ctx: AgentContext) -> Positioning:
    proposal = ctx.positioning_proposal or {}
    risks = compute_risks(ctx)

    proposed = list(proposal.get("olivesoft_advantages", []))
    if delivered_projects(ctx):
        advantages = proposed
    else:
        advantages = []
        if proposed:
            risks.append(
                "Avantages OliveSoft non retenus : aucun projet livré trouvé dans la base "
                "pour les prouver. À compléter avec de vraies références."
            )

    return Positioning(
        olivesoft_advantages=advantages,
        risks=risks,
        recommended_strategy=proposal.get("recommended_strategy", ""),
        differentiators_to_emphasize=list(proposal.get("differentiators_to_emphasize", [])),
    )