import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

from rag.main import app
from rag.embeddings import EmbeddingError
from rag.supabase_client import RagConfigurationError


RESULT = {
    "id": "row-1",
    "content": "Amina knows FastAPI",
    "doc_type": "cv",
    "source_file": "fake_cvs.json",
    "metadata": {"record_id": "CV-1", "skills": ["FastAPI"]},
    "similarity": 0.91,
    "ranking_score": 0.91,
}


@pytest.mark.asyncio
async def test_health_is_public_and_does_not_initialize_providers():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_reports_model_outage_as_retryable_503():
    with patch("rag.main.get_model", side_effect=EmbeddingError("model unavailable")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_ready_returns_ready_after_model_loads():
    with patch("rag.main.get_model", return_value=object()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_query_requires_internal_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/query", json={"text": "FastAPI engineer"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_query_returns_record_metadata():
    with patch("rag.main.query_knowledge_base", return_value=[RESULT]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/query",
                json={"text": "FastAPI engineer", "doc_type": "cv"},
                headers={"X-Internal-Token": "test-token"},
            )
    assert response.status_code == 200
    assert response.json()[0]["metadata"]["record_id"] == "CV-1"


@pytest.mark.asyncio
async def test_query_rejects_bad_limits_and_extra_fields():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/query",
            json={"text": "valid query", "top_k": 100, "unexpected": True},
            headers={"X-Internal-Token": "test-token"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_query_returns_empty_list_when_nothing_matches():
    with patch("rag.main.query_knowledge_base", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/query",
                json={"text": "catering and facilities management"},
                headers={"X-Internal-Token": "test-token"},
            )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_stats_requires_internal_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/stats")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_stats_returns_a_count_per_type():
    counts = {"cv": 48, "project": 126, "tool": 30}
    with patch("rag.main.get_supabase", return_value=object()), patch(
        "rag.main.count_records", return_value=counts
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/stats", headers={"X-Internal-Token": "test-token"})
    assert response.status_code == 200
    assert response.json() == counts


class _PagingClient:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args):
        return self

    def order(self, _column):
        return self

    def range(self, _start, _end):
        return self

    def execute(self):
        if isinstance(self._data, Exception):
            raise self._data
        return SimpleNamespace(data=self._data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count", [RuntimeError("html instead of json"), None], ids=["unreachable", "null_data"]
)
async def test_stats_unreachable_or_malformed_is_retryable_503(count):
    with patch("rag.main.get_supabase", return_value=_PagingClient(count)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/stats", headers={"X-Internal-Token": "test-token"})
    body = response.json()
    assert response.status_code == 503
    assert body["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert body["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_stats_without_supabase_configuration_is_503():
    with patch("rag.main.get_supabase", side_effect=RagConfigurationError("Missing SUPABASE_URL")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/stats", headers={"X-Internal-Token": "test-token"})
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
