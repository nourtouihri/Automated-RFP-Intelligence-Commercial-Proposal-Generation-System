from .conftest import TOKEN


def test_tenders_pass_through_with_status_filter(client, seen):
    client.get("/api/tenders?status=new")
    assert seen[-1].url.path == "/tenders" and seen[-1].url.params["status"] == "new"


def test_tenders_without_filter_sends_no_status(client, seen):
    client.get("/api/tenders")
    assert "status" not in seen[-1].url.params


def test_tender_id_is_url_encoded(client, seen):
    client.get("/api/tenders/Lot%203%20%2F%20North")
    assert seen[-1].url.raw_path == b"/tenders/Lot%203%20%2F%20North"


def test_upstream_call_carries_token_and_request_id(client, seen):
    r = client.get("/api/tenders", headers={"X-Request-ID": "req-1"})
    assert seen[-1].headers["X-Internal-Token"] == TOKEN
    assert seen[-1].headers["X-Request-ID"] == "req-1"
    assert r.headers["X-Request-ID"] == "req-1"
    assert TOKEN not in r.text


def test_research_routes_pass_through(client, seen):
    client.get("/api/research")
    assert seen[-1].url.host == "research" and seen[-1].url.path == "/research"
    client.get("/api/research/Lot%203%20%2F%20North")
    assert seen[-1].url.raw_path == b"/research/Lot%203%20%2F%20North"


def test_research_audit_route_is_encoded_and_not_swallowed_by_the_id_route(client, seen):
    client.get("/api/research/tender-001/audit")
    assert seen[-1].url.host == "research" and seen[-1].url.path == "/research/tender-001/audit"
    client.get("/api/research/Lot%203%20%2F%20North/audit")
    assert seen[-1].url.raw_path == b"/research/Lot%203%20%2F%20North/audit"


def test_proposal_route_passes_safe_id_through(client, seen):
    client.get("/api/proposal/tender-001")
    assert seen[-1].url.host == "proposal" and seen[-1].url.path == "/proposal/tender-001"


def test_proposal_route_refuses_unsafe_id(client, seen):
    r = client.get("/api/proposal/..%2Fsecrets")
    assert r.status_code == 400 and r.json()["error"]["field"] == "tender_id"
    assert r.json()["error"]["message"] == "invalid tender id"
    assert seen == []


def test_proposal_route_refuses_space_and_overlong_ids(client, seen):
    assert client.get("/api/proposal/Lot%203").status_code == 400
    assert client.get("/api/proposal/" + "a" * 65).status_code == 400
    assert seen == []


def test_upstream_not_found_keeps_the_envelope(client_with_one_deck):
    r = client_with_one_deck.get("/api/proposal/tender-002")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "No deck generated for tender"


def test_proposals_skip_tenders_without_a_deck(client_with_one_deck):
    assert list(client_with_one_deck.get("/api/proposals").json()) == ["tender-001"]


def test_proposals_never_ask_for_unsafe_ids(client_with_one_deck, seen):
    client_with_one_deck.get("/api/proposals")
    proposal_paths = [r.url.path for r in seen if r.url.host == "proposal"]
    assert proposal_paths == ["/proposal/tender-001", "/proposal/tender-002"]


def test_proposals_propagate_other_upstream_failures(client_with_proposal_down):
    r = client_with_proposal_down.get("/api/proposals")
    assert r.status_code == 503 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_library_stats_passes_through_to_rag(client, seen):
    r = client.get("/api/library/stats")
    assert r.status_code == 200
    assert seen[-1].method == "GET" and seen[-1].url.host == "rag" and seen[-1].url.path == "/stats"
    assert seen[-1].headers["X-Internal-Token"] == TOKEN


def test_library_stats_outage_is_a_retryable_503(settings, seen):
    import httpx
    from fastapi.testclient import TestClient

    from server.app import create_app

    def down(request):
        seen.append(request)
        raise httpx.ConnectError("refused", request=request)

    with TestClient(create_app(settings, httpx.MockTransport(down))) as c:
        r = c.get("/api/library/stats")
    assert r.status_code == 503
    assert r.json()["error"]["retryable"] is True
    assert len(seen) == 1


def test_insights_routes_pass_through(client, seen):
    """GET /api/insights (no id) is the feeder; its shape is asserted in
    test_insights_absent_for_a_tender_is_listed_as_missing."""
    client.get("/api/insights/tender-001")
    assert seen[-1].url.raw_path == b"/insights/tender-001"
    client.get("/api/insights/Lot%203%20%2F%20North")
    assert seen[-1].url.raw_path == b"/insights/Lot%203%20%2F%20North"


def test_post_insights_uses_the_run_timeout(settings, seen):
    import httpx
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import Settings
    from server.tests.conftest import _ok, _recording

    run_settings = Settings(
        token=TOKEN, services={
            "detection": "http://detection:8000", "insights": "http://insights:8006",
        },
        timeouts={"default": 30, "insights": 160})
    with TestClient(create_app(run_settings, _recording(seen, _ok))) as c:
        r = c.post("/api/insights/tender-001")
    assert r.status_code == 200
    assert seen[-1].method == "POST"
    assert seen[-1].url.host == "insights" and seen[-1].url.path == "/insights/tender-001"


def test_insights_absent_for_a_tender_is_listed_as_missing(settings, seen):
    """The insights-all feeder skips tenders the agent has no run for."""
    import httpx
    from fastapi.testclient import TestClient

    from server.app import create_app

    tender_seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        if "/tenders" == request.url.path.rstrip("/").replace("/api", ""):
            tender_seen.append(request)
            return httpx.Response(200, json=[{"id": "tender-001"}, {"id": "tender-002"}])
        if "tender-001" in request.url.path:
            return httpx.Response(200, json={"budget": {"method": "explicit"}})
        return httpx.Response(
            404, json={"error": {"code": "NOT_FOUND", "message": "no insights for tender",
                                 "retryable": False, "request_id": None}})

    with TestClient(create_app(settings, httpx.MockTransport(answer))) as c:
        out = c.get("/api/insights").json()
    assert set(out) == {"tender-001"}
    assert out["tender-001"]["budget"]["method"] == "explicit"
