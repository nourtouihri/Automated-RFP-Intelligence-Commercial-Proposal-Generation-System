"""F3: the RAG app speaks the shared error envelope.

The service previously raised ``HTTPException(503, detail=str(exc))``, so a
retrieval/embedding/config outage surfaced as FastAPI's ``{"detail": ...}`` —
no stable ``code``, no ``retryable`` (the one signal that tells the caller to
retry), no request id. These pin 401 and 503 in the shared shape.
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

from rag.main import app  # noqa: E402
from rag.query import RetrievalError  # noqa: E402

TOKEN = {"X-Internal-Token": "test-token"}
VALID_BODY = {"text": "senior MuleSoft integration", "top_k": 3}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_missing_token_is_enveloped_401():
    async with _client() as client:
        resp = await client.post("/query", json=VALID_BODY)
    body = resp.json()
    assert resp.status_code == 401
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert body["error"]["retryable"] is False
    assert resp.headers["X-Request-ID"] == body["error"]["request_id"]


@pytest.mark.asyncio
async def test_upstream_outage_is_enveloped_503_retryable(monkeypatch):
    def _boom(*args, **kwargs):
        raise RetrievalError("connection refused")

    monkeypatch.setattr("rag.main.query_knowledge_base", _boom)
    async with _client() as client:
        resp = await client.post("/query", json=VALID_BODY, headers=TOKEN)
    body = resp.json()
    assert resp.status_code == 503
    assert body["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert body["error"]["retryable"] is True
    assert "detail" not in body


@pytest.mark.asyncio
async def test_inbound_request_id_is_echoed():
    async with _client() as client:
        resp = await client.get("/health", headers={"X-Request-ID": "rag-42"})
    assert resp.headers["X-Request-ID"] == "rag-42"
