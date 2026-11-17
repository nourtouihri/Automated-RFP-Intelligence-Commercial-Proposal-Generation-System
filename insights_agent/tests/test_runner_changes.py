import pytest

from insights_agent import runner


def make_llm(answers):
    """Fake LLM: each item is a JSON string to return, or an Exception to raise."""
    it = iter(answers)
    calls = {"n": 0}

    async def llm(message, system=None):
        calls["n"] += 1
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    llm.calls = calls
    return llm


async def fake_search(query):
    return []


async def fake_fetch(url):
    return ""


class RateLimitError(Exception):
    status_code = 429


@pytest.mark.asyncio
async def test_nested_arguments_are_unwrapped():
    llm = make_llm([
        '{"action": "search_web", "thought": "x", "arguments": {"query": "mulesoft hr cost"}}',
        '{"action": "finish", "thought": "done"}',
    ])
    run = await runner.run_agent(
        {"id": "t", "title": "T"}, llm_call=llm,
        web_search=fake_search, fetch_page=fake_fetch,
    )
    assert run.trace[0]["args"] == {"query": "mulesoft hr cost"}
    assert run.trace[0]["error"] != "invalid_query"


@pytest.mark.asyncio
async def test_llm_error_detail_is_recorded(monkeypatch):
    monkeypatch.setattr(runner, "LLM_RETRY_PAUSE_S", 0)
    llm = make_llm([RateLimitError()] * 6)
    run = await runner.run_agent({"id": "t", "title": "T"}, llm_call=llm)
    assert run.stop_reason == "llm_error"
    assert run.trace[0]["error"] == "llm_call_failed"
    assert run.trace[0]["llm_error_detail"] == "RateLimitError:429"
    assert llm.calls["n"] == 6  # 2 turns x (1 call + 2 retries)


@pytest.mark.asyncio
async def test_llm_recovers_after_one_failure(monkeypatch):
    monkeypatch.setattr(runner, "LLM_RETRY_PAUSE_S", 0)
    llm = make_llm([RateLimitError(), '{"action": "finish", "thought": "done"}'])
    run = await runner.run_agent({"id": "t", "title": "T"}, llm_call=llm)
    assert run.stop_reason == "finished"
    assert run.trace[0].get("llm_retried") is True