"""The loop: the LLM chooses, but limits, validation and confidence belong to the code."""

import asyncio
import json

import pytest

from insights_agent import runner
from insights_agent.prompts import EXTRACTOR_SYSTEM
from insights_agent.runner import MAX_INVALID, run_agent

TENDER = {
    "id": "t1", "title": "Refonte portail", "issuer": "Mairie",
    "description": "Budget estimé : 500 000 TND. Cautionnement provisoire : 5 000 TND.",
}
VAGUE = {"id": "t2", "title": "Portail web", "issuer": "Ville", "description": "Un portail web."}

TASKS = [
    {"name": "Connexion des sources", "days": 25, "reason": "5 sources à 5 jours chacune"},
    {"name": "Tableau de bord", "days": 30, "reason": "Trois rôles utilisateurs"},
]
PAGE = "Le marché a été attribué à Acme Systems pour un montant de 120 000 TND."


@pytest.fixture(autouse=True)
def no_retry_pause(monkeypatch):
    """The single LLM retry waits 2 s in production; tests must not."""
    monkeypatch.setattr(runner, "LLM_RETRY_PAUSE_S", 0.0)


def scripted(replies, extractor_facts=None, seen=None):
    """Agent turns come from `replies`; extractor calls (by system prompt) get facts."""
    queue = list(replies)

    async def llm(text, system=None):
        if system == EXTRACTOR_SYSTEM:
            return json.dumps({"facts": extractor_facts or []})
        if seen is not None:
            seen.append(text)
        item = queue.pop(0) if queue else {"action": "read_tender"}
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)
    return llm


def go(tender, llm, **kw):
    return asyncio.run(run_agent(tender, llm_call=llm, **kw))


def test_full_run_uses_the_explicit_budget_and_completes():
    llm = scripted([
        {"action": "read_tender", "thought": "besoin des exigences"},
        {"action": "find_explicit_budget"},
        {"action": "propose_workload", "tasks": TASKS},
        {"action": "compute_budget"},
        {"action": "finish"},
    ])
    run = go(TENDER, llm)
    assert [s["action"] for s in run.trace] == [
        "read_tender", "find_explicit_budget", "propose_workload", "compute_budget", "finish",
    ]
    assert run.stop_reason == "finished"
    assert run.insights.budget.method == "explicit"
    assert run.insights.budget.likely == 500_000
    assert run.insights.confidence == "high" and run.insights.status == "complete"


def test_agent_stops_at_max_turns_and_the_code_still_computes_a_budget():
    run = go(VAGUE, scripted([{"action": "read_tender"}] * 20), max_turns=3)
    assert run.stop_reason == "max_turns"
    assert len([s for s in run.trace if not s.get("auto")]) == 3
    assert run.insights.budget.method == "none" and run.insights.confidence == "low"
    assert run.insights.status == "partial"


def test_unknown_action_is_refused_and_the_loop_continues():
    run = go(VAGUE, scripted([{"action": "delete_database"}, {"action": "finish"}]))
    assert run.trace[0]["error"] == "unknown_action"
    assert run.stop_reason == "finished"


def test_repeated_invalid_output_stops_the_agent():
    run = go(VAGUE, scripted(["pas du json"] * 5))
    assert run.stop_reason == "invalid_output"
    assert len([s for s in run.trace if not s.get("auto")]) == MAX_INVALID
    assert run.insights.status == "unavailable"


def test_time_limit_stops_before_any_llm_call():
    seen = []
    run = go(VAGUE, scripted([], seen=seen), time_limit_s=0)
    assert run.stop_reason == "time_limit" and seen == []


def test_llm_failure_does_not_crash():
    # Each turn consumes two errors (call + single retry), so give plenty.
    run = go(VAGUE, scripted([TimeoutError("down")] * 10))
    assert run.trace[0]["error"] == "llm_call_failed"
    assert run.stop_reason == "llm_error"
    assert run.insights.status == "unavailable"


def test_a_retried_llm_call_is_visible_in_the_trace():
    run = go(VAGUE, scripted([TimeoutError("429"), {"action": "finish"}]))
    assert run.trace[0]["action"] == "finish"
    assert run.trace[0].get("llm_retried") is True


def test_finish_without_compute_budget_is_fixed_by_the_code():
    run = go(TENDER, scripted([{"action": "find_explicit_budget"}, {"action": "finish"}]))
    assert run.insights.budget.method == "explicit"
    assert run.trace[-1].get("auto") is True


def test_confidence_and_numbers_from_the_model_are_ignored():
    run = go(VAGUE, scripted([{"action": "finish", "confidence": "high", "budget": 999_999}]))
    assert run.insights.budget.method == "none"
    assert run.insights.confidence == "low"


def test_competitors_come_from_verified_facts_with_their_url():
    value = "attribué à Acme Systems pour un montant de 120 000 TND"
    fact = {"category": "competitor", "value": value, "name": "Acme Systems", "confidence": "high"}

    async def search(query):
        return [{"url": "https://a.example/1", "title": "t", "snippet": "s"}]

    async def fetch(url):
        return PAGE

    llm = scripted(
        [{"action": "search_web", "query": "marché portail attribué"}, {"action": "finish"}],
        extractor_facts=[fact],
    )
    run = go(VAGUE, llm, web_search=search, fetch_page=fetch)
    assert [c.name for c in run.insights.competitors] == ["Acme Systems"]
    assert run.insights.competitors[0].evidence == ["https://a.example/1"]


def test_tool_results_are_fed_back_to_the_llm():
    seen = []
    go(TENDER, scripted([{"action": "read_tender"}, {"action": "finish"}], seen=seen))
    assert "Turn 1: read_tender" in seen[1] and "Refonte portail" in seen[1]