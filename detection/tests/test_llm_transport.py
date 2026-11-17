"""§4.1 never-500 boundary at the *transport* level.

The edge-case matrix asserts "LLM/garbage output -> never 500", but it was only
exercised at the *text* level (the model returns prose instead of JSON). The
other half — a provider or gateway answering HTTP 200 with a body that is not
the documented object — went through ``resp.json()["content"][0]["text"]`` and
raised ``TypeError``, which the normalize wrappers did not catch, so a provider
hiccup became a raw 500 on the ingest path.

These tests pin the contract: the transport raises only the classes its callers
already handle (``ValueError``/``httpx.HTTPError``), and the endpoint degrades
to an accepted, flagged record instead of a 500.
"""

import os

import pytest

os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

from detection import llm as llm_mod
from detection.normalize import normalize_tender
from shared import store

TOKEN_HEADER = {"X-Internal-Token": "test-token"}

FULL = {
    "title": "Integration Platform Upgrade",
    "issuer": "ACME Group",
    "deadline": "2026-12-01",
    "raw_text": "Deliver a MuleSoft integration layer unifying HR and payroll systems.",
    "source": "simulated_feed",
}

# A 200 whose body is not ``{"content": [{"text": ...}]}`` or
# ``{"choices": [{"message": {"content": ...}}]}``. Proxies, WAFs and gateways
# return HTML/plain bodies with a 200; a provider bug can return ``null``.
MALFORMED_BODIES = [
    [],  # bare array: the original probe -> TypeError
    None,  # JSON null
    "a plain string body",  # text/plain masquerading as JSON
    {"content": []},  # documented key, empty list
    {"content": None},
    {"content": [{"type": "text"}]},  # element missing the text field
    {"choices": []},  # OpenAI shape, empty
]


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _client_returning(body):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _FakeResponse(body)

    return _FakeClient


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "transport.db")
    store.init_db()
    yield


def _configure_anthropic(monkeypatch, body):
    # Patch the module attribute the transport uses, not httpx globally: the
    # test client itself is an httpx.AsyncClient.
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _client_returning(body))
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", MALFORMED_BODIES)
async def test_transport_raises_value_error_on_malformed_body(body, monkeypatch):
    _configure_anthropic(monkeypatch, body)
    with pytest.raises(ValueError):
        await llm_mod.llm_call("hello")


@pytest.mark.asyncio
async def test_transport_returns_text_on_well_formed_anthropic_body(monkeypatch):
    """Guard the happy path: every other test mocks ``llm_call`` at the
    normalize layer, so a mistake in ``_dig_text`` would otherwise ship unseen."""
    _configure_anthropic(monkeypatch, {"content": [{"type": "text", "text": "hello world"}]})
    assert await llm_mod.llm_call("hi") == "hello world"


@pytest.mark.asyncio
async def test_transport_returns_text_on_well_formed_openai_body(monkeypatch):
    monkeypatch.setattr(
        llm_mod.httpx, "AsyncClient", _client_returning({"choices": [{"message": {"content": "hi there"}}]})
    )
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "k")
    assert await llm_mod.llm_call("hi") == "hi there"


@pytest.mark.asyncio
async def test_transport_returns_text_on_well_formed_ollama_body(monkeypatch):
    monkeypatch.setattr(
        llm_mod.httpx, "AsyncClient", _client_returning({"choices": [{"message": {"content": "local"}}]})
    )
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_URL", "http://localhost:11434/v1/chat/completions")
    assert await llm_mod.llm_call("hi") == "local"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", MALFORMED_BODIES)
async def test_normalize_never_raises_on_malformed_provider_body(body, monkeypatch):
    _configure_anthropic(monkeypatch, body)
    tender, _is_existing = await normalize_tender(FULL)
    # Degraded, not dead: deterministic fallback requirements + a warning.
    assert tender.requirements
    assert "llm_unavailable" in tender.quality.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize("body", MALFORMED_BODIES)
async def test_ingest_endpoint_returns_200_not_500(body, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from detection.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Arm the fake only after the test client is built, so the client keeps
        # the real AsyncClient while the app's outbound call uses the fake.
        monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _client_returning(body))
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
        resp = await client.post("/tenders/ingest", json=FULL, headers=TOKEN_HEADER)

    assert resp.status_code == 200, resp.text
    assert "llm_unavailable" in resp.json()["quality"]["warnings"]
