"""F3: the research app speaks the shared error envelope.

Before this, research registered its own ``@app.exception_handler(Exception)``
returning a bare ``{"error": "Internal server error"}`` with no request id, and
404s came back as FastAPI's ``{"detail": ...}``. A caller that branches on
``code``/``retryable`` (the n8n workflow) therefore had to parse a second,
undocumented shape. These pin the one-shape contract and the X-Request-ID echo.
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

from research.main import app  # noqa: E402
from shared import store  # noqa: E402

TOKEN = {"X-Internal-Token": "test-token"}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init_db()
    yield


def _client(**kwargs) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, **kwargs), base_url="http://test")


@pytest.mark.asyncio
async def test_missing_token_is_enveloped_401():
    async with _client() as client:
        resp = await client.post("/research/t1")
    body = resp.json()
    assert resp.status_code == 401
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"]
    assert resp.headers["X-Request-ID"] == body["error"]["request_id"]


@pytest.mark.asyncio
async def test_missing_tender_is_enveloped_404_not_detail():
    async with _client() as client:
        resp = await client.post("/research/does-not-exist", headers=TOKEN)
    body = resp.json()
    assert resp.status_code == 404
    assert body["error"]["code"] == "NOT_FOUND"
    assert "detail" not in body


@pytest.mark.asyncio
async def test_inbound_request_id_is_echoed():
    async with _client() as client:
        resp = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"


@pytest.mark.asyncio
async def test_unhandled_error_is_internal_envelope_not_bare_error(monkeypatch):
    class _BoomRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr("research.main.Runner", _BoomRunner)
    async with _client(raise_app_exceptions=False) as client:
        resp = await client.post("/research/t1", headers=TOKEN)
    body = resp.json()
    assert resp.status_code == 500
    assert body["error"]["code"] == "INTERNAL"
    assert body["error"]["retryable"] is True
    assert "detail" not in body
