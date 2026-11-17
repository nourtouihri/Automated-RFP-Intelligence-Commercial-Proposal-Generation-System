import pytest

from insights_agent.tools.budget_tools import detect_country_count, propose_workload
from insights_agent.tools.context import AgentContext


def tasks(days):
    return {"tasks": [{"name": "All work", "days": days, "profile": "standard",
                       "reason": "everything needed for the project"}]}


def make_ctx(text):
    return AgentContext(tender={"id": "t", "raw_text": text})


def test_detects_country_count():
    assert detect_country_count("HR data across 11 countries") == 11
    assert detect_country_count("dans 5 pays") == 5
    assert detect_country_count("no number here") is None


@pytest.mark.asyncio
async def test_low_workload_rejected_once_then_accepted():
    ctx = make_ctx("integration across 11 countries")
    first = await propose_workload(tasks(96), ctx)
    assert first["ok"] is False and first["error"] == "workload_too_low"
    second = await propose_workload(tasks(96), ctx)
    assert second["ok"] is True and "warning" in second


@pytest.mark.asyncio
async def test_enough_days_passes_first_time():
    ctx = make_ctx("integration across 11 countries")
    r = await propose_workload(tasks(140), ctx)
    assert r["ok"] is True and "warning" not in r


@pytest.mark.asyncio
async def test_no_country_no_floor():
    ctx = make_ctx("small portal project")
    r = await propose_workload(tasks(20), ctx)
    assert r["ok"] is True