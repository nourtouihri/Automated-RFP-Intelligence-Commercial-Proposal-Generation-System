import pytest

from insights_agent.tools.budget_tools import compute_budget
from insights_agent.tools.context import AgentContext


@pytest.mark.asyncio
async def test_two_comparables_are_ignored():
    ctx = AgentContext(tender={"id": "t"})
    ctx.comparable_values_tnd = [1000.0, 2000.0]
    ctx.comparable_sources = ["https://a.example", "https://b.example"]
    await compute_budget({}, ctx)
    assert ctx.budget.method != "comparables"


@pytest.mark.asyncio
async def test_three_comparables_are_used():
    ctx = AgentContext(tender={"id": "t"})
    ctx.comparable_values_tnd = [1000.0, 2000.0, 3000.0]
    ctx.comparable_sources = ["https://a.example", "https://b.example", "https://c.example"]
    await compute_budget({}, ctx)
    assert ctx.budget.method == "comparables"