import json

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app import create_app

from .conftest import _recording

REVIEW = {"deck_generated_at": "2026-01-01T00:00:00+00:00", "sections": {"summary": "approved"},
          "signed_off_by": "Ama"}


def test_review_get_is_forwarded_to_the_proposal_service(client, seen):
    assert client.get("/api/proposal/tender.001/review").status_code == 200
    request = seen[-1]
    assert request.method == "GET" and request.url.host == "proposal"
    assert request.url.raw_path.decode() == "/proposal/tender.001/review"


def test_review_put_forwards_the_body_with_the_default_timeout(client, seen):
    assert client.put("/api/proposal/tender-001/review", json=REVIEW).status_code == 200
    request = seen[-1]
    assert request.method == "PUT" and request.url.path == "/proposal/tender-001/review"
    assert json.loads(request.content) == REVIEW
    assert request.extensions["timeout"]["read"] == 30


@pytest.mark.parametrize("method", ["get", "put"])
def test_review_refuses_unsafe_ids_before_any_upstream_call(client, seen, method):
    for bad in ("%2E%2E", "a%20b%24"):
        kwargs = {"json": REVIEW} if method == "put" else {}
        assert getattr(client, method)(f"/api/proposal/{bad}/review", **kwargs).status_code == 400
    assert seen == []


def test_review_conflict_passes_the_envelope_through_and_is_not_retried(settings, seen):
    envelope = {"error": {"code": "BAD_REQUEST", "message": "The deck was regenerated; reload the review",
                          "field": None, "retryable": False, "request_id": None}}
    transport = _recording(seen, lambda request: httpx.Response(409, json=envelope))
    with TestClient(create_app(settings, transport)) as c:
        r = c.put("/api/proposal/tender-001/review", json=REVIEW)
    assert r.status_code == 409
    assert r.json()["error"]["message"] == "The deck was regenerated; reload the review"
    assert len(seen) == 1
