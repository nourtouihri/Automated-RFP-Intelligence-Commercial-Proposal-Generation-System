"""Tools: the LLM only receives verified facts; every failure becomes a result, not a crash."""

import asyncio
import json

from insights_agent.tools import ALLOWED_ACTIONS, AgentContext, run_tool
from insights_agent.tools.tender_tools import TENDER_TEXT_CAP

PAGE = (
    "Le marché de refonte du portail a été attribué à Acme Systems pour un "
    "montant de 120 000 TND."
)

TENDER = {
    "id": "t1",
    "title": "Refonte portail",
    "issuer": "Mairie",
    "description": "Budget estimé : 500 000 TND. Cautionnement provisoire : 5 000 TND.",
}


def call(name, args, ctx):
    return asyncio.run(run_tool(name, args, ctx))


def fake_llm(facts):
    async def llm(text, system=None):
        return json.dumps({"facts": facts})
    return llm


def amount_fact(value):
    return {"category": "comparable_budget", "value": value, "name": None, "confidence": "medium"}


def competitor_fact(value, name):
    return {"category": "competitor", "value": value, "name": name, "confidence": "high"}


def web_ctx(facts, urls=("https://a.example/1",), fetch=None):
    async def search(query):
        return [{"url": u, "title": "t", "snippet": "s"} for u in urls]

    async def default_fetch(url):
        return PAGE

    return AgentContext(
        tender=TENDER, llm_call=fake_llm(facts), web_search=search,
        fetch_page=fetch or default_fetch,
    )


TASKS = [
    {"name": "Connexion des sources", "days": 25, "reason": "5 sources à 5 jours chacune"},
    {"name": "Tableau de bord", "days": 30, "reason": "Trois rôles utilisateurs"},
    {"name": "Tests et déploiement", "days": 15, "reason": "Recette puis mise en production"},
]


# --- tender tools -----------------------------------------------------------


def test_read_tender_returns_text_and_title():
    r = call("read_tender", {}, AgentContext(tender=TENDER))
    assert r["ok"] and r["tender_id"] == "t1" and "Refonte portail" in r["text"]


def test_read_tender_is_capped():
    big = {"id": "x", "description": "a" * (TENDER_TEXT_CAP * 2)}
    r = call("read_tender", {}, AgentContext(tender=big))
    assert len(r["text"]) == TENDER_TEXT_CAP and r["truncated"]


def test_find_explicit_budget_ignores_the_guarantee():
    ctx = AgentContext(tender=TENDER)
    r = call("find_explicit_budget", {}, ctx)
    assert r["found"] and [a["value_tnd"] for a in r["amounts"]] == [500_000]


# --- web --------------------------------------------------------------------


def test_search_web_keeps_only_verified_facts():
    ctx = web_ctx([amount_fact("montant de 120 000 TND"), amount_fact("montant de 900 000 TND")])
    r = call("search_web", {"query": "marché portail attribué"}, ctx)
    assert r["ok"] and len(r["comparable_budgets"]) == 1
    assert r["rejected_unverified"] == 1
    assert ctx.comparable_values_tnd == [120_000.0]
    assert ctx.comparable_sources == ["https://a.example/1"]


def test_search_web_collects_competitors():
    value = "attribué à Acme Systems pour un montant de 120 000 TND"
    ctx = web_ctx([competitor_fact(value, "Acme Systems")])
    r = call("search_web", {"query": "marché portail attribué"}, ctx)
    assert [c["name"] for c in r["competitors"]] == ["Acme Systems"]


def test_search_web_does_not_read_the_same_url_twice():
    ctx = web_ctx([amount_fact("montant de 120 000 TND")])
    call("search_web", {"query": "marché portail"}, ctx)
    second = call("search_web", {"query": "marché portail bis"}, ctx)
    assert second["pages_read"] == 0 and len(ctx.comparable_values_tnd) == 1


def test_search_web_without_provider():
    r = call("search_web", {"query": "marché portail"}, AgentContext(tender=TENDER))
    assert r == {"ok": False, "error": "search_unavailable"}


def test_search_web_provider_failure_is_a_result_not_a_crash():
    async def boom(query):
        raise TimeoutError("down")

    ctx = AgentContext(tender=TENDER, web_search=boom, fetch_page=lambda u: None)
    assert call("search_web", {"query": "marché portail"}, ctx)["error"] == "search_failed"


def test_one_failing_page_does_not_stop_the_others():
    async def fetch(url):
        if url.endswith("/1"):
            raise ConnectionError("blocked")
        return PAGE

    ctx = web_ctx(
        [amount_fact("montant de 120 000 TND")],
        urls=("https://a.example/1", "https://a.example/2"), fetch=fetch,
    )
    r = call("search_web", {"query": "marché portail"}, ctx)
    assert r["pages_read"] == 1 and ctx.comparable_values_tnd == [120_000.0]


# --- RAG --------------------------------------------------------------------


def test_search_past_projects_normalizes_rows():
    async def rag(query):
        return [
            {"title": "Portail ville A", "budget_tnd": 90_000},
            {"name": "Appli B", "budget": "110 000 TND"},
            {"title": "Sans prix"},
            "not a dict",
        ]

    ctx = AgentContext(tender=TENDER, rag_query=rag)
    r = call("search_past_projects", {"query": "portail web"}, ctx)
    assert r["ok"] and len(r["projects"]) == 3
    assert ctx.past_values_tnd == [90_000.0, 110_000.0]
    assert r["reference_median_tnd"] == 100_000


def test_search_past_projects_without_rag():
    r = call("search_past_projects", {"query": "portail web"}, AgentContext(tender=TENDER))
    assert r["error"] == "rag_unavailable"


# --- workload and budget ----------------------------------------------------


def test_propose_workload_valid():
    ctx = AgentContext(tender=TENDER, daily_rate=400)
    r = call("propose_workload", {"tasks": TASKS}, ctx)
    assert r["ok"] and r["total_days"] == 70 and r["effort_likely_tnd"] == 28_000
    assert r["reference_check"]["checked"] is False


def test_propose_workload_rejects_absurd_days():
    bad = [{"name": "Petit tableau", "days": 5000, "reason": "Valeur absurde du modèle"}]
    r = call("propose_workload", {"tasks": bad}, AgentContext(tender=TENDER))
    assert not r["ok"] and r["error"] == "invalid_workload" and r["details"]


def test_propose_workload_flags_an_estimate_far_below_past_projects():
    ctx = AgentContext(tender=TENDER, daily_rate=400)
    ctx.past_values_tnd = [90_000.0]
    r = call("propose_workload", {"tasks": TASKS}, ctx)
    assert r["reference_check"]["suspicious"] is True


def test_compute_budget_explicit_wins():
    ctx = AgentContext(tender=TENDER, daily_rate=400)
    call("find_explicit_budget", {}, ctx)
    call("propose_workload", {"tasks": TASKS}, ctx)
    r = call("compute_budget", {}, ctx)
    assert r["budget"]["method"] == "explicit" and r["budget"]["likely"] == 500_000


def test_compute_budget_falls_back_to_effort():
    ctx = AgentContext(tender={"id": "t2", "description": "Un portail web."}, daily_rate=400)
    call("propose_workload", {"tasks": TASKS}, ctx)
    r = call("compute_budget", {}, ctx)
    assert r["budget"]["method"] == "effort" and r["budget"]["likely"] == 28_000


def test_compute_budget_with_nothing_returns_none_not_a_guess():
    ctx = AgentContext(tender={"id": "t3", "description": "Un portail web."})
    r = call("compute_budget", {}, ctx)
    assert r["budget"]["method"] == "none" and r["budget"]["likely"] is None


# --- registry ---------------------------------------------------------------


def test_unknown_action_is_refused():
    assert call("delete_everything", {}, AgentContext(tender=TENDER))["error"] == "unknown_action"


def test_a_crashing_tool_becomes_an_error_result():
    r = call("search_web", None, AgentContext(tender=TENDER))
    assert r == {"ok": False, "error": "tool_crashed"}


def test_allowed_actions_are_the_fixed_list():
    assert ALLOWED_ACTIONS == {
        "read_tender", "find_explicit_budget", "search_web",
        "search_past_projects", "propose_workload", "propose_positioning",
        "compute_budget", "finish",
    }