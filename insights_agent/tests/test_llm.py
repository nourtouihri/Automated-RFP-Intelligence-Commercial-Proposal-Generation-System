"""Own LLM client: provider choice, request shape, clear errors. No network."""

import asyncio

import pytest

from insights_agent import llm


def run(coro):
    return asyncio.run(coro)


def fake_post(response, seen):
    async def post(url, headers, payload):
        seen.update(url=url, headers=headers, payload=payload)
        return response
    return post


def test_anthropic_request_and_parse(monkeypatch):
    seen = {}
    monkeypatch.setenv("INSIGHTS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(llm, "_post", fake_post({"content": [{"type": "text", "text": "ok"}]}, seen))
    assert run(llm.default_llm_call("hi", system="sys")) == "ok"
    assert seen["payload"]["system"] == "sys"
    assert seen["headers"]["x-api-key"] == "k"


def test_openai_request_and_parse(monkeypatch):
    seen = {}
    monkeypatch.setenv("INSIGHTS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(llm, "_post", fake_post({"choices": [{"message": {"content": "ok"}}]}, seen))
    assert run(llm.default_llm_call("hi", system="sys")) == "ok"
    assert seen["payload"]["messages"][0] == {"role": "system", "content": "sys"}


def test_ollama_needs_no_key(monkeypatch):
    seen = {}
    monkeypatch.setenv("INSIGHTS_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(llm, "_post", fake_post({"message": {"content": "ok"}}, seen))
    assert run(llm.default_llm_call("hi")) == "ok"
    assert seen["url"].endswith("/api/chat")


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("INSIGHTS_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError):
        run(llm.default_llm_call("hi"))


def test_unknown_provider_is_refused(monkeypatch):
    monkeypatch.setenv("INSIGHTS_LLM_PROVIDER", "nope")
    with pytest.raises(llm.LLMConfigError):
        run(llm.default_llm_call("hi"))


def test_without_provider_the_team_function_is_used(monkeypatch):
    import sys, types

    monkeypatch.delenv("INSIGHTS_LLM_PROVIDER", raising=False)
    mod = types.ModuleType("detection.llm")

    async def team(text, system=None):
        return "team"

    mod.llm_call = team
    monkeypatch.setitem(sys.modules, "detection.llm", mod)
    assert run(llm.default_llm_call("hi")) == "team"

def test_groq_request_and_parse(monkeypatch):
    seen = {}
    monkeypatch.setenv("INSIGHTS_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(llm, "_post", fake_post({"choices": [{"message": {"content": "ok"}}]}, seen))
    assert run(llm.default_llm_call("hi", system="sys")) == "ok"
    assert "groq.com" in seen["url"]
    assert seen["headers"]["Authorization"] == "Bearer k"