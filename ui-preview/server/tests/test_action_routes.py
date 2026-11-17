import json

N1 = {"id": "notice-1", "title": "First"}
N2 = {"id": "notice-2", "title": ""}
N3 = {"id": "notice-3", "title": "Third"}


def test_unknown_ingest_source_is_refused(client, seen):
    r = client.post("/api/ingest/UAE", json={"page": 1})
    assert r.status_code == 400 and r.json()["error"]["field"] == "source"
    assert seen == []


def test_ingest_forwards_page_to_ingestion_with_ingest_timeout(client, seen):
    client.post("/api/ingest/TED", json={"page": 3})
    request = seen[-1]
    assert request.url.host == "ingestion" and request.url.path == "/ingest/TED"
    assert json.loads(request.content) == {"page": 3}
    assert request.extensions["timeout"]["read"] == 60


def test_ingest_accepts_sam(client, seen):
    client.post("/api/ingest/SAM", json={"page": 1})
    assert seen[-1].url.path == "/ingest/SAM"


def test_ingest_without_page_is_a_validation_envelope(client, seen):
    r = client.post("/api/ingest/TED", json={})
    assert r.status_code == 422 and r.json()["error"]["field"] == "body.page"
    assert seen == []


def test_missing_sam_key_passes_through_unretryable(client_sam_500):
    r = client_sam_500.post("/api/ingest/SAM", json={"page": 1})
    e = r.json()["error"]
    assert r.status_code == 500
    assert e["code"] == "INTERNAL" and e["retryable"] is False and "INGEST_API_KEYS" in e["message"]


def test_tender_ingest_forwards_body_unchanged(client, seen):
    body = {"id": "t-9", "title": "Roads", "unknown": [1, 2]}
    client.post("/api/tenders/ingest", json=body)
    request = seen[-1]
    assert request.url.host == "detection" and request.url.path == "/tenders/ingest"
    assert json.loads(request.content) == body
    assert request.extensions["timeout"]["read"] == 30


def test_status_change_is_forwarded_with_the_id_encoded(client, seen):
    r = client.patch("/api/tenders/Lot%203%20%2F%20North/status", json={"status": "archived"})
    assert r.status_code == 200
    request = seen[-1]
    assert request.method == "PATCH" and request.url.host == "detection"
    assert request.url.raw_path == b"/tenders/Lot%203%20%2F%20North/status"
    assert json.loads(request.content) == {"status": "archived"}
    assert request.extensions["timeout"]["read"] == 30


def test_status_change_passes_the_upstream_envelope_through(client_without_tender):
    r = client_without_tender.patch("/api/tenders/nope/status", json={"status": "active"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_seed_uses_ingest_timeout(client, seen):
    client.post("/api/tenders/seed")
    assert seen[-1].url.host == "detection" and seen[-1].url.path == "/tenders/seed"
    assert seen[-1].extensions["timeout"]["read"] == 60


def test_send_reports_each_notice(client_rejecting_second, seen):
    r = client_rejecting_second.post("/api/notices/send", json={"notices": [N1, N2, N3]})
    rows = r.json()["results"]
    assert [row["ok"] for row in rows] == [True, False, True]
    assert [row["id"] for row in rows] == ["notice-1", "notice-2", "notice-3"]
    assert rows[0]["tender"] == {"id": "ok"} and rows[0]["error"] is None
    assert rows[1]["tender"] is None
    assert rows[1]["error"]["error"]["code"] == "TENDER_INVALID_FIELD"
    assert rows[1]["error"]["error"]["field"] == "title"
    assert len(seen) == 3
    assert [json.loads(s.content) for s in seen] == [N1, N2, N3]
    assert all(s.url.host == "detection" and s.url.path == "/tenders/ingest" for s in seen)


def test_send_records_an_unreachable_service_and_keeps_going(client_timing_out, seen):
    rows = client_timing_out.post("/api/notices/send", json={"notices": [N1, N3]}).json()["results"]
    assert [row["ok"] for row in rows] == [False, False]
    assert rows[0]["error"]["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert rows[0]["error"]["error"]["retryable"] is True
    assert len(seen) == 2


def test_send_with_no_notices_makes_no_calls(client, seen):
    assert client.post("/api/notices/send", json={"notices": []}).json() == {"results": []}
    assert seen == []


def test_send_refuses_a_malformed_body(client, seen):
    for body in ({"notices": "x"}, {"notices": [1]}, {}, ["a"]):
        r = client.post("/api/notices/send", json=body)
        assert r.status_code == 422 and "error" in r.json()
    assert seen == []


def test_research_force_is_forwarded(client, seen):
    client.post("/api/research/tender-012?force=true")
    assert seen[-1].url.params["force"] == "true"
    assert seen[-1].url.host == "research" and seen[-1].url.path == "/research/tender-012"
    assert seen[-1].extensions["timeout"]["read"] == 150


def test_research_without_force_sends_no_force(client, seen):
    client.post("/api/research/tender-012")
    assert "force" not in seen[-1].url.params


def test_research_id_is_url_encoded(client, seen):
    client.post("/api/research/Lot%203%20%2F%20North")
    assert seen[-1].url.raw_path == b"/research/Lot%203%20%2F%20North"


def test_query_forwards_body_to_rag(client, seen):
    body = {"text": "road works", "top_k": 3}
    client.post("/api/query", json=body)
    assert seen[-1].url.host == "rag" and seen[-1].url.path == "/query"
    assert json.loads(seen[-1].content) == body


def test_post_is_never_retried_on_timeout(client_timing_out, seen):
    r = client_timing_out.post("/api/research/tender-001")
    assert len(seen) == 1
    assert r.status_code == 503 and r.json()["error"]["retryable"] is True


def test_action_calls_carry_the_token_and_request_id(client, seen):
    from .conftest import TOKEN

    r = client.post("/api/query", json={"text": "abc"}, headers={"X-Request-ID": "req-7"})
    assert seen[-1].headers["X-Internal-Token"] == TOKEN
    assert seen[-1].headers["X-Request-ID"] == "req-7"
    assert r.headers["X-Request-ID"] == "req-7" and TOKEN not in r.text
