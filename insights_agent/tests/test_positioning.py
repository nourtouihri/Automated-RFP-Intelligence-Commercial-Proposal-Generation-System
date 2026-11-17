"""Risks come from the code; the LLM's pitch is validated."""

import asyncio
import json

from insights_agent.positioning import build_positioning
from insights_agent.prompts import EXTRACTOR_SYSTEM
from insights_agent.runner import run_agent
from insights_agent.tools import AgentContext, run_tool

TASKS = [
    {"name": "Connexion des sources", "days": 25, "reason": "5 sources à 5 jours chacune"},
    {"name": "Tableau de bord", "days": 30, "reason": "Trois rôles utilisateurs"},
    {"name": "Tests et déploiement", "days": 15, "reason": "Recette puis mise en production"},
]
PITCH = {
    "olivesoft_advantages": ["Expérience en tableaux de bord décisionnels"],
    "differentiators_to_emphasize": ["Équipe locale à Tunis"],
    "recommended_strategy": "Mettre en avant les références locales.",
}


def call(name, args, ctx):
    return asyncio.run(run_tool(name, args, ctx))


def test_valid_pitch_is_stored():
    ctx = AgentContext(tender={"id": "t"})
    ctx.past_projects = [{"title": "Projet livré", "amount_tnd": None, "delivered": True}]
    assert call("propose_positioning", PITCH, ctx)["ok"]
    p = build_positioning(ctx)
    assert p.olivesoft_advantages == PITCH["olivesoft_advantages"]
    assert p.recommended_strategy == PITCH["recommended_strategy"]


def test_unknown_key_in_pitch_is_rejected():
    ctx = AgentContext(tender={"id": "t"})
    r = call("propose_positioning", {**PITCH, "price": 5}, ctx)
    assert r["error"] == "invalid_positioning"
    assert ctx.positioning_proposal is None


def test_too_many_items_are_rejected():
    ctx = AgentContext(tender={"id": "t"})
    r = call("propose_positioning", {"olivesoft_advantages": ["avantage"] * 6}, ctx)
    assert r["error"] == "invalid_positioning"


def test_no_verified_competitor_is_a_risk_not_a_finding():
    ctx = AgentContext(tender={"id": "t"})
    assert any("Aucun concurrent vérifié" in r for r in build_positioning(ctx).risks)


def test_no_budget_is_a_risk():
    ctx = AgentContext(tender={"id": "t", "description": "Un portail web."})
    call("compute_budget", {}, ctx)
    assert any("Aucun budget" in r for r in build_positioning(ctx).risks)


def test_written_budget_below_our_effort_is_a_risk():
    ctx = AgentContext(tender={"id": "t", "description": "Budget estimé : 20 000 TND."}, daily_rate=400)
    call("find_explicit_budget", {}, ctx)
    call("propose_workload", {"tasks": TASKS}, ctx)
    call("compute_budget", {}, ctx)
    assert any("inférieur à notre estimation" in r for r in build_positioning(ctx).risks)


def test_effort_far_from_past_projects_is_a_risk():
    ctx = AgentContext(tender={"id": "t", "description": "Un portail."}, daily_rate=400)
    ctx.past_values_tnd = [90_000.0]
    call("propose_workload", {"tasks": TASKS}, ctx)
    call("compute_budget", {}, ctx)
    assert any("s'écarte fortement" in r for r in build_positioning(ctx).risks)


def test_run_agent_returns_positioning_in_the_insights():
    replies = [
        {"action": "propose_positioning", **PITCH},
        {"action": "finish"},
    ]

    async def llm(text, system=None):
        if system == EXTRACTOR_SYSTEM:
            return json.dumps({"facts": []})
        return json.dumps(replies.pop(0))

    run = asyncio.run(run_agent({"id": "t", "title": "Portail"}, llm_call=llm))
    assert run.insights.positioning.recommended_strategy == PITCH["recommended_strategy"]
    assert run.insights.positioning.risks