import asyncio

from insights_agent.adapters import _is_delivered, _project_title, make_rag_query
from insights_agent.budget import resolve_budget
from insights_agent.positioning import build_positioning, compute_risks
from insights_agent.schemas import Workload, WorkloadTask
from insights_agent.tools.context import AgentContext
from insights_agent.tools.rag_tools import search_past_projects

PFE = {
    "record_id": "olivesoft-020", "domain": ["HR", "Salesforce"],
    "tech_stack": ["Salesforce", "Apex", "Lightning", "SQL"],
    "relationship": "pfe_internship_project", "outcome": "proposed",
}


def ctx_with_proposal(past_projects):
    ctx = AgentContext(tender={"id": "t"})
    ctx.past_projects = past_projects
    ctx.positioning_proposal = {
        "olivesoft_advantages": ["Experience MuleSoft"],
        "recommended_strategy": "Proposed approach: x",
        "differentiators_to_emphasize": [],
    }
    return ctx


def test_advantages_dropped_without_delivered_project():
    pos = build_positioning(ctx_with_proposal([]))
    assert pos.olivesoft_advantages == []
    assert any("non retenus" in r for r in pos.risks)


def test_advantages_dropped_for_internship_project():
    pos = build_positioning(ctx_with_proposal([{"title": "x", "delivered": False}]))
    assert pos.olivesoft_advantages == []


def test_advantages_kept_with_delivered_project():
    pos = build_positioning(ctx_with_proposal([{"title": "x", "delivered": True}]))
    assert pos.olivesoft_advantages == ["Experience MuleSoft"]


def test_single_weak_comparable_does_not_create_reference_risk():
    ctx = AgentContext(tender={"id": "t"})
    ctx.workload = Workload(tasks=[WorkloadTask(name="All", days=100, reason="everything in the project")])
    ctx.budget = resolve_budget(person_days=100)
    ctx.comparable_values_tnd = [3100.0]
    assert not any("s'écarte" in r for r in compute_risks(ctx))


def test_title_is_readable():
    assert _project_title(PFE, "projects_clean.json") == "olivesoft-020 | HR/Salesforce | Salesforce, Apex, Lightning"
    assert _project_title({}, "projects_clean.json") == "projects_clean.json"


def test_internship_is_not_delivered():
    assert _is_delivered(PFE) is False
    assert _is_delivered({}) is False
    assert _is_delivered({"relationship": "client_project", "outcome": "delivered"}) is True


def test_rag_adapter_returns_title_and_delivered_flag():
    row = {"metadata": PFE, "source_file": "projects_clean.json", "content": "no price here"}
    rag = make_rag_query(lambda text: [row])
    out = asyncio.run(rag("hr"))
    assert out == [{"title": "olivesoft-020 | HR/Salesforce | Salesforce, Apex, Lightning",
                    "budget_tnd": None, "delivered": False}]


def test_delivered_flag_reaches_the_context():
    async def rag(q):
        return [{"title": "A", "budget_tnd": None, "delivered": True},
                {"title": "B", "budget_tnd": None, "delivered": False},
                {"title": "C", "budget_tnd": None}]

    ctx = AgentContext(tender={"id": "t"}, rag_query=rag)
    asyncio.run(search_past_projects({"query": "hr integration"}, ctx))
    assert [p["delivered"] for p in ctx.past_projects] == [True, False, False]