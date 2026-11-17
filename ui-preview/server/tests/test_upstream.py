import httpx
import pytest

from server.upstream import Upstream
from shared.errors import ApiError, ErrorCode

from .conftest import BrokenBody, _recording


def test_upstream_call_carries_token_and_request_id(upstream, seen):
    upstream.call("detection", "GET", "/tenders", request_id="abc123")
    assert seen[-1].headers["X-Internal-Token"] == "dev-token"
    assert seen[-1].headers["X-Request-ID"] == "abc123"


def test_call_returns_status_and_parsed_json(upstream, seen):
    assert upstream.call("detection", "GET", "/tenders") == (200, {"ok": True})
    assert str(seen[-1].url) == "http://detection:8000/tenders"


def test_call_sends_json_body_and_params(upstream, seen):
    upstream.call("rag", "POST", "/query", json={"text": "x"}, params={"k": "1"})
    assert seen[-1].read() == b'{"text":"x"}'
    assert seen[-1].url.params["k"] == "1"


def test_empty_success_body_is_none(upstream_answering):
    assert upstream_answering(204, "").call("detection", "DELETE", "/x") == (204, None)


def test_service_down_is_retryable_and_named(upstream_refusing):
    with pytest.raises(ApiError) as e:
        upstream_refusing.call("research", "GET", "/research")
    assert e.value.code == ErrorCode.UPSTREAM_UNAVAILABLE and e.value.retryable
    assert e.value.status_code == 503
    assert "research" in e.value.message.lower()


def test_timeout_says_the_work_may_still_be_running(upstream_timing_out):
    with pytest.raises(ApiError) as e:
        upstream_timing_out.call("proposal", "POST", "/proposals/t1")
    assert e.value.code == ErrorCode.UPSTREAM_UNAVAILABLE and e.value.retryable
    assert e.value.status_code == 503
    assert "proposal" in e.value.message.lower()
    assert "still be running" in e.value.message


def test_a_post_is_never_retried(upstream_refusing, seen):
    with pytest.raises(ApiError):
        upstream_refusing.call("research", "POST", "/research/t1")
    assert len(seen) == 1


def test_detail_body_is_wrapped(upstream_answering):
    with pytest.raises(ApiError) as e:
        upstream_answering(404, {"detail": "Tender not found"}).call("detection", "GET", "/tenders/x")
    assert e.value.code == ErrorCode.NOT_FOUND and e.value.message == "Tender not found"
    assert e.value.status_code == 404 and not e.value.retryable


def test_detail_body_with_unlisted_status(upstream_answering):
    with pytest.raises(ApiError) as e:
        upstream_answering(409, {"detail": "busy"}).call("research", "POST", "/research/t")
    assert e.value.code == ErrorCode.BAD_REQUEST and e.value.status_code == 409


def test_upstream_envelope_is_reraised_as_is(upstream_answering):
    body = {
        "error": {
            "code": "RAW_TEXT_TOO_LONG",
            "message": "too long",
            "field": "raw_text",
            "retryable": False,
            "request_id": "up1",
        }
    }
    with pytest.raises(ApiError) as e:
        upstream_answering(422, body).call("detection", "POST", "/tenders")
    assert e.value.code == ErrorCode.RAW_TEXT_TOO_LONG
    assert (e.value.message, e.value.field, e.value.status_code) == ("too long", "raw_text", 422)
    assert not e.value.retryable


def test_envelope_with_unknown_code_falls_back_to_status(upstream_answering):
    body = {"error": {"code": "BRAND_NEW", "message": "m", "field": None, "retryable": True}}
    with pytest.raises(ApiError) as e:
        upstream_answering(503, body).call("detection", "GET", "/x")
    assert e.value.code == ErrorCode.UPSTREAM_UNAVAILABLE and e.value.retryable


def test_html_502_is_wrapped(upstream_answering):
    with pytest.raises(ApiError) as e:
        upstream_answering(502, "<html>Bad Gateway</html>").call("rag", "POST", "/query")
    assert e.value.code == ErrorCode.UPSTREAM_UNAVAILABLE and e.value.retryable
    assert e.value.status_code == 503 and "rag" in e.value.message.lower()
    assert "Bad Gateway" not in e.value.message


def test_non_json_success_is_unavailable(upstream_answering):
    with pytest.raises(ApiError) as e:
        upstream_answering(200, "not json").call("rag", "GET", "/x")
    assert e.value.code == ErrorCode.UPSTREAM_UNAVAILABLE


def test_stream_returns_the_response_and_carries_the_token(upstream_answering, seen):
    response = upstream_answering(200, "PK-bytes").stream("proposal", "/files/t1/deck.pptx", request_id="r1")
    assert response.read() == b"PK-bytes"
    assert seen[-1].headers["X-Internal-Token"] == "dev-token"
    assert seen[-1].headers["X-Request-ID"] == "r1"
    response.close()


def test_stream_errors_use_the_same_mapping(upstream_answering):
    with pytest.raises(ApiError) as e:
        upstream_answering(404, {"detail": "no file"}).stream("proposal", "/files/t1/x")
    assert e.value.code == ErrorCode.NOT_FOUND


def test_stream_when_service_is_down(upstream_refusing):
    with pytest.raises(ApiError) as e:
        upstream_refusing.stream("proposal", "/files/t1/x")
    assert e.value.code == ErrorCode.UPSTREAM_UNAVAILABLE


def test_stream_error_body_read_failure_is_unavailable(settings, seen):
    upstream = Upstream(settings, _recording(seen, lambda request: httpx.Response(502, stream=BrokenBody())))
    with pytest.raises(ApiError) as e:
        upstream.stream("proposal", "/files/t1/x")
    assert e.value.code == ErrorCode.UPSTREAM_UNAVAILABLE and e.value.retryable
    assert e.value.status_code == 503 and "proposal" in e.value.message.lower()


def test_probe_sends_no_token_and_reports_status(upstream, seen):
    assert upstream.probe("n8n", "/healthz") == 200
    assert "X-Internal-Token" not in seen[-1].headers
    assert str(seen[-1].url) == "http://n8n:5678/healthz"


def test_probe_is_none_when_unreachable(upstream_refusing):
    assert upstream_refusing.probe("rag", "/health") is None
