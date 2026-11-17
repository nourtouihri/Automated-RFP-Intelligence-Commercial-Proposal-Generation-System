import httpx
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.ids import is_deck_safe

from .conftest import BrokenBody, _recording

PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PPTX_BODY = b"PK\x03\x04deck-bytes"
MISSING = {
    "error": {
        "code": "NOT_FOUND",
        "message": "File not found",
        "field": None,
        "retryable": False,
        "request_id": None,
    }
}


def _pptx_only(request: httpx.Request) -> httpx.Response:
    if request.url.raw_path.decode() == "/proposal/tender-001/files/tender-001.pptx":
        return httpx.Response(
            200,
            content=PPTX_BODY,
            headers={
                "content-type": PPTX_TYPE,
                "content-disposition": 'attachment; filename="tender-001.pptx"',
            },
        )
    return httpx.Response(404, json=MISSING)


@pytest.fixture
def client_with_pptx(settings, seen):
    with TestClient(create_app(settings, _recording(seen, _pptx_only))) as c:
        yield c


def test_proxy_streams_the_file(client_with_pptx, seen):
    response = client_with_pptx.get("/api/files/tender-001/tender-001.pptx")
    assert response.status_code == 200 and response.content.startswith(b"PK")
    assert response.headers["content-type"] == PPTX_TYPE
    assert response.headers["content-disposition"] == 'attachment; filename="tender-001.pptx"'
    assert seen[-1].headers["X-Internal-Token"] == "dev-token"
    assert str(seen[-1].url) == "http://proposal:8003/proposal/tender-001/files/tender-001.pptx"


def test_proxy_forwards_a_missing_file_as_the_envelope(client_with_pptx):
    response = client_with_pptx.get("/api/files/tender-001/olivesoft.db")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "path",
    [
        "/api/files/tender-001/..%2F..%2F.env",
        "/api/files/tender-001/a%5Cb.pptx",
        "/api/files/tender-001/..",
        "/api/files/tender-001/.",
        "/api/files/tender-001/...",
        "/api/files/tender-001/a/b.pptx",
        "/api/files/..%2Ftender-001/x.pptx",
        "/api/files/../x.pptx",
        "/api/files/./x.pptx",
        "/api/files/Lot%203/x.pptx",
        "/api/files/tender-001/",
    ],
)
def test_proxy_refuses_unsafe_ids_and_names_without_calling_upstream(client_with_pptx, seen, path):
    response = client_with_pptx.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert seen == []


def test_proxy_encodes_the_name_upstream(client_with_pptx, seen):
    client_with_pptx.get("/api/files/tender-001/my deck.pptx")
    assert seen[-1].url.raw_path.decode() == "/proposal/tender-001/files/my%20deck.pptx"


def test_proxy_maps_a_body_read_failure_to_unavailable(settings, seen):
    def answer(request):
        return httpx.Response(200, stream=BrokenBody(), headers={"content-type": "text/csv"})

    with TestClient(create_app(settings, _recording(seen, answer))) as c:
        response = c.get("/api/files/tender-001/tender-001.matrix.csv")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True


@pytest.mark.parametrize("value", [".", "..", "..."])
def test_dot_only_ids_are_not_deck_safe(value):
    assert not is_deck_safe(value)


def test_dot_only_proposal_id_never_reaches_upstream(client, seen):
    assert client.get("/api/proposal/%2E%2E").status_code == 400
    assert client.post("/api/proposal/%2E%2E", json={}).status_code == 400
    assert seen == []
