import json
from typing import Any, Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings
from server.upstream import Upstream

TOKEN = "dev-token"
SERVICES = {
    "detection": "http://detection:8000",
    "rag": "http://rag:8001",
    "research": "http://research:8002",
    "proposal": "http://proposal:8003",
    "insights": "http://insights:8006",
    "ingestion": "http://ingestion:8004",
    "n8n": "http://n8n:5678",
}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        token=TOKEN,
        services=dict(SERVICES),
        timeouts={"default": 30, "research": 150, "deck": 180, "ingest": 60,
                  "insights": 160},
    )


@pytest.fixture
def seen() -> list[httpx.Request]:
    return []


def _recording(seen: list[httpx.Request], answer: Callable[[httpx.Request], httpx.Response]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer(request)

    return httpx.MockTransport(handler)


class BrokenBody(httpx.SyncByteStream):
    def __iter__(self):
        raise httpx.ReadError("connection reset")
        yield b""


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


@pytest.fixture
def transport(seen) -> httpx.MockTransport:
    return _recording(seen, _ok)


@pytest.fixture
def upstream(settings, transport) -> Upstream:
    return Upstream(settings, transport)


@pytest.fixture
def client(settings, transport):
    with TestClient(create_app(settings, transport)) as c:
        yield c


@pytest.fixture
def upstream_refusing(settings, seen) -> Upstream:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    return Upstream(settings, _recording(seen, refuse))


@pytest.fixture
def upstream_timing_out(settings, seen) -> Upstream:
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    return Upstream(settings, _recording(seen, time_out))


@pytest.fixture
def upstream_answering(settings, seen) -> Callable[..., Upstream]:
    def make(status: int, body: Any) -> Upstream:
        def answer(request: httpx.Request) -> httpx.Response:
            if isinstance(body, str):
                return httpx.Response(status, text=body)
            return httpx.Response(status, json=body)

        return Upstream(settings, _recording(seen, answer))

    return make


@pytest.fixture
def client_with_rag_down(settings, seen):
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.host == "rag":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"status": "ok"})

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        yield c


DECK = {
    "tender_id": "tender-001",
    "kind": "proposal",
    "deck": {},
    "warnings": [],
    "artifacts": {},
    "generated_at": "2026-01-01T00:00:00Z",
}
NO_DECK = {
    "error": {
        "code": "NOT_FOUND",
        "message": "No deck generated for tender",
        "field": None,
        "retryable": False,
        "request_id": None,
    }
}


def _tenders_with_one_deck(request: httpx.Request) -> httpx.Response:
    path = request.url.raw_path.decode().split("?")[0]
    if path == "/tenders":
        return httpx.Response(
            200, json=[{"id": "tender-001"}, {"id": "tender-002"}, {"id": "Lot 3 / North"}]
        )
    if path == "/proposal/tender-001":
        return httpx.Response(200, json=DECK)
    if path == "/proposal/tender-002":
        return httpx.Response(404, json=NO_DECK)
    return httpx.Response(500, json={"detail": "unexpected"})


@pytest.fixture
def client_with_one_deck(settings, seen):
    with TestClient(create_app(settings, _recording(seen, _tenders_with_one_deck))) as c:
        yield c


@pytest.fixture
def client_with_proposal_down(settings, seen):
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.host == "proposal":
            raise httpx.ConnectError("refused", request=request)
        return _tenders_with_one_deck(request)

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        yield c


SAM_NO_KEY = {
    "error": {
        "code": "INTERNAL",
        "message": "SAM.gov ingestion needs INGEST_API_KEYS set on the ingestion service.",
        "field": None,
        "retryable": False,
        "request_id": None,
    }
}
REJECTED_NOTICE = {
    "error": {
        "code": "TENDER_INVALID_FIELD",
        "message": "title is empty",
        "field": "title",
        "retryable": False,
        "request_id": None,
    }
}


@pytest.fixture
def client_sam_500(settings, seen):
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json=SAM_NO_KEY)

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        yield c


@pytest.fixture
def client_rejecting_second(settings, seen):
    def answer(request: httpx.Request) -> httpx.Response:
        if len(seen) == 2:
            return httpx.Response(422, json=REJECTED_NOTICE)
        return httpx.Response(200, json={"id": "ok"})

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        yield c


@pytest.fixture
def client_timing_out(settings, seen):
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with TestClient(create_app(settings, _recording(seen, time_out))) as c:
        yield c


TENDER = {
    "id": "tender-001",
    "title": "HRIS",
    "issuer": "Meridian",
    "requirements": ["MuleSoft layer", "MDM"],
}
CV_HIT = {
    "id": "cv-chunk-1",
    "content": "Senior integration engineer",
    "doc_type": "cv",
    "source_file": "cv_1.json",
    "metadata": {"record_id": "cv_1"},
    "similarity": 0.8,
    "ranking_score": 0.8,
}
PROJECT_HIT = {
    "id": "project-chunk-1",
    "content": "HRIS rollout",
    "doc_type": "project",
    "source_file": "project_1.json",
    "metadata": {"record_id": "project_1"},
    "similarity": 0.7,
    "ranking_score": 0.7,
}
IDLESS_HIT = {**PROJECT_HIT, "id": "", "metadata": {"record_id": "project_2"}}


def _generation_answers(request: httpx.Request, *, proposal: Callable[[], httpx.Response]):
    path = request.url.raw_path.decode().split("?")[0]
    if path == "/tenders/tender-001":
        return httpx.Response(200, json=TENDER)
    if path == "/query":
        doc_type = json.loads(request.content)["doc_type"]
        return httpx.Response(200, json=[CV_HIT] if doc_type == "cv" else [PROJECT_HIT, IDLESS_HIT])
    if path == "/proposal/tender-001":
        return proposal()
    return httpx.Response(500, json={"detail": "unexpected"})


@pytest.fixture
def client_generating(settings, seen):
    def answer(request: httpx.Request) -> httpx.Response:
        return _generation_answers(request, proposal=lambda: httpx.Response(200, json=DECK))

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        yield c


@pytest.fixture
def client_proposal_timing_out(settings, seen):
    def time_out() -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=None)

    def answer(request: httpx.Request) -> httpx.Response:
        return _generation_answers(request, proposal=time_out)

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        yield c


@pytest.fixture
def client_without_tender(settings, seen):
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json=NO_DECK)

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        yield c
