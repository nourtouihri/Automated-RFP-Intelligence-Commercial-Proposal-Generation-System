import pytest

from insights_agent.tools import TOOLS, run_tool
from insights_agent.tools.context import AgentContext


@pytest.mark.asyncio
async def test_tool_disabled_after_rag_failure(monkeypatch):
    calls = {"n": 0}

    async def failing(args, ctx):
        calls["n"] += 1
        return {"ok": False, "error": "rag_failed"}

    monkeypatch.setitem(TOOLS, "search_past_projects", failing)
    ctx = AgentContext(tender={"id": "t"})

    first = await run_tool("search_past_projects", {"query": "x"}, ctx)
    second = await run_tool("search_past_projects", {"query": "y"}, ctx)

    assert first["error"] == "rag_failed"
    assert second["error"] == "tool_disabled"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_invalid_query_does_not_disable(monkeypatch):
    async def bad_args(args, ctx):
        return {"ok": False, "error": "invalid_query"}

    monkeypatch.setitem(TOOLS, "search_web", bad_args)
    ctx = AgentContext(tender={"id": "t"})

    await run_tool("search_web", {}, ctx)
    assert "search_web" not in ctx.disabled_tools