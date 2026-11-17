"""The proposal-scoped LLM_* override rules (proposal/llm_adapter._setting).

Every shared LLM_* variable can be shadowed per-deployment by PROPOSAL_LLM_*;
an empty override (docker-compose exports unset vars as '') means "use the
shared value", and with neither set the old KeyError is raised."""

import asyncio
import json

import httpx
import pytest

from proposal.llm_adapter import _setting, openai_call
import proposal.main as service


def test__setting_falls_back_to_the_shared_value(monkeypatch):
    monkeypatch.delenv("PROPOSAL_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "shared-model")
    assert _setting("LLM_MODEL") == "shared-model"


def test__setting_prefers_the_proposal_override(monkeypatch):
    monkeypatch.setenv("PROPOSAL_LLM_MODEL", "deck-model")
    monkeypatch.setenv("LLM_MODEL", "shared-model")
    assert _setting("LLM_MODEL") == "deck-model"


def test__setting_treats_an_empty_override_as_no_override(monkeypatch):
    monkeypatch.setenv("PROPOSAL_LLM_URL", "")
    monkeypatch.setenv("LLM_URL", "http://shared/v1")
    assert _setting("LLM_URL") == "http://shared/v1"


def test__setting_without_either_variable_is_a_key_error(monkeypatch):
    monkeypatch.delenv("PROPOSAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(KeyError):
        _setting("LLM_MODEL")


def test__llm_uses_the_proposal_url_even_without_the_shared_one(monkeypatch):
    used = {}

    def fake_openai_call(*a, **k):
        used["transport"] = True
        return lambda s, u: None

    monkeypatch.setattr(service, "openai_call", fake_openai_call)
    monkeypatch.delenv("LLM_URL", raising=False)
    monkeypatch.delenv("PROPOSAL_LLM_URL", raising=False)
    service._llm()
    assert "transport" not in used  # neither set: the default transport stays

    monkeypatch.setenv("PROPOSAL_LLM_URL", "http://deck-only/v1")
    service._llm()
    assert "transport" in used  # the proposal-only URL flips it to the adapter


def test__verifier_is_off_without_a_model_of_its_own(monkeypatch):
    # the guard deliberately never falls back to the writer's model: without
    # PROPOSAL_VERIFIER_LLM_MODEL the grounding check is off, and the note says
    # why instead of quietly returning no judge
    monkeypatch.delenv("PROPOSAL_VERIFIER_LLM_MODEL", raising=False)
    monkeypatch.delenv("PROPOSAL_VERIFIER_LLM_API_KEY", raising=False)
    verifier, note = service._verifier()
    assert verifier is None
    assert note == "verifier: off (no PROPOSAL_VERIFIER_LLM_MODEL)"


def test__verifier_judges_on_the_named_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "writer-model")
    monkeypatch.setenv("PROPOSAL_LLM_MODEL", "writer-model")
    monkeypatch.setenv("PROPOSAL_VERIFIER_LLM_MODEL", "critic-model")
    monkeypatch.delenv("PROPOSAL_VERIFIER_LLM_API_KEY", raising=False)
    verifier, note = service._verifier()
    assert verifier is not None and verifier.model == "critic-model"
    assert note is None  # a different model: nothing to confess


def test__verifier_on_the_writers_model_confesses_it(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "writer-model")
    monkeypatch.setenv("PROPOSAL_LLM_MODEL", "writer-model")
    monkeypatch.setenv("PROPOSAL_VERIFIER_LLM_MODEL", "writer-model")
    monkeypatch.delenv("PROPOSAL_VERIFIER_LLM_API_KEY", raising=False)
    verifier, note = service._verifier()
    assert verifier is not None and verifier.model == "writer-model"
    assert note is not None and "blind spots" in note


def test_openai_call_sends_the_proposal_model_key_and_shared_url(monkeypatch):
    monkeypatch.setenv("LLM_URL", "https://shared.test/v1")
    monkeypatch.setenv("PROPOSAL_LLM_MODEL", "deck-model")
    monkeypatch.delenv("PROPOSAL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "shared-key")
    monkeypatch.setenv("PER_CALL_TIMEOUT_SECONDS", "120")
    captured: dict = {}

    def transport(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    call = openai_call(transport=httpx.MockTransport(transport))
    reply = asyncio.run(call("system", "user"))

    assert reply.text == "ok"
    assert captured["model"] == "deck-model"  # override, not LLM_MODEL
    assert captured["auth"] == "Bearer shared-key"  # key falls back to shared


def test_openai_call_key_hides_the_shared_key_with_an_override(monkeypatch):
    monkeypatch.setenv("LLM_URL", "https://shared.test/v1")
    monkeypatch.delenv("PROPOSAL_LLM_MODEL", raising=False)
    monkeypatch.setenv("PROPOSAL_LLM_API_KEY", "deck-key")
    captured: dict = {}

    def transport(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    call = openai_call(transport=httpx.MockTransport(transport))
    asyncio.run(call("s", "u"))
    assert captured["auth"] == "Bearer deck-key"
