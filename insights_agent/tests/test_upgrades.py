"""Profile-weighted cost and sourced competitor strengths/weaknesses."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from insights_agent.budget import workload_to_budget
from insights_agent.extractor import VerifiedFact, extract_insights
from insights_agent.positioning import compute_risks
from insights_agent.runner import build_competitors
from insights_agent.schemas import Workload, WorkloadTask
from insights_agent.tools import AgentContext

URL = "https://example.com/p"
PAGE = ("Acme Systems a remporté le marché pour 120 000 TND. "
        "Acme Systems est certifié ISO 27001. Acme Systems a livré avec trois mois de retard.")


def task(days, profile=None):
    kw = {"profile": profile} if profile else {}
    return WorkloadTask(name="Tâche test", days=days, reason="Justification détaillée", **kw)


def run(facts):
    async def llm(text, system=None):
        return json.dumps({"facts": facts})
    return asyncio.run(extract_insights(PAGE, URL, llm))


def fact(category, value, name="Acme Systems"):
    return {"category": category, "value": value, "name": name, "confidence": "medium"}


def test_profiles_change_the_cost():
    w = Workload(tasks=[task(10, "junior"), task(10, "senior")])
    assert workload_to_budget(w, daily_rate=400).likely == 8_400  # (7 + 14) x 400


def test_default_profile_is_standard():
    assert workload_to_budget(Workload(tasks=[task(10)]), daily_rate=400).likely == 4_000


def test_unknown_profile_is_rejected():
    with pytest.raises(ValidationError):
        task(10, "wizard")


def test_sourced_strength_is_accepted():
    r = run([fact("competitor_strength", "Acme Systems est certifié ISO 27001")])
    assert [f.category for f in r.facts] == ["competitor_strength"]


def test_strength_with_invented_name_is_rejected():
    r = run([fact("competitor_strength", "Acme Systems est certifié ISO 27001", name="Globex")])
    assert r.facts == [] and r.rejected[0]["reason"] == "name_not_in_page"


def test_invented_weakness_is_rejected():
    r = run([fact("competitor_weakness", "Acme Systems a fait faillite")])
    assert r.facts == [] and r.rejected[0]["reason"] == "value_not_in_page"


def test_competitor_gets_strengths_and_weaknesses_from_sources():
    ctx = AgentContext(tender={"id": "t"})
    ctx.web_facts = [
        VerifiedFact("competitor", "Acme a remporté le marché", "Acme", (), "high", URL),
        VerifiedFact("competitor_strength", "Acme est certifié ISO", "Acme", (), "high", URL),
        VerifiedFact("competitor_weakness", "Acme a livré en retard", "ACME", (), "high", URL),
    ]
    [c] = build_competitors(ctx)
    assert c.strengths == ["Acme est certifié ISO"] and c.weaknesses == ["Acme a livré en retard"]
    assert c.evidence == [URL]
    assert any("point fort" in r for r in compute_risks(ctx))


def test_no_source_means_empty_lists():
    ctx = AgentContext(tender={"id": "t"})
    ctx.web_facts = [VerifiedFact("competitor", "Acme a gagné", "Acme", (), "high", URL)]
    [c] = build_competitors(ctx)
    assert c.strengths == [] and c.weaknesses == []