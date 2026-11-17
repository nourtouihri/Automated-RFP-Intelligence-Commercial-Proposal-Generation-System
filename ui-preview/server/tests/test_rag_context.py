import json

from server.rag_context import hits_by_record, rag_query


def test_rag_query_matches_n8n():
    t = {"title": "HRIS", "issuer": "Meridian", "requirements": ["MuleSoft layer", "MDM"]}
    assert rag_query(t) == "HRIS\nMeridian\nMuleSoft layer\nMDM"


def test_rag_query_skips_missing_parts_and_reads_requirement_text():
    t = {"title": "HRIS", "issuer": None, "requirements": [{"text": "MDM"}, "", {"id":3}]}
    assert rag_query(t) == 'HRIS\nMDM\n{"id":3}'


def test_generate_sends_both_match_lists(client, seen):
    client.post("/api/proposal/tender-001", json={})
    bodies = [json.loads(r.content) for r in seen if r.url.path == "/query"]
    assert [b["doc_type"] for b in bodies] == ["cv", "project"]
    assert all(b["top_k"] == 5 and b["similarity_threshold"] == 0.20 for b in bodies)
    sent = json.loads(next(r for r in seen if r.url.path == "/proposal/tender-001").content)
    assert set(sent) == {"cv_matches", "project_matches"}


def test_generate_timeout_is_retryable(client_proposal_timing_out):
    e = client_proposal_timing_out.post("/api/proposal/tender-001", json={}).json()["error"]
    assert e["code"] == "UPSTREAM_UNAVAILABLE" and e["retryable"] is True
    assert "may still be running" in e["message"]


def test_generate_sends_the_query_and_keeps_only_hits_with_an_id(client_generating, seen):
    deck = client_generating.post("/api/proposal/tender-001", json={}).json()
    queries = [json.loads(r.content) for r in seen if r.url.path == "/query"]
    assert {q["text"] for q in queries} == {"HRIS\nMeridian\nMuleSoft layer\nMDM"}
    sent = json.loads(next(r for r in seen if r.url.path == "/proposal/tender-001").content)
    assert [h["id"] for h in sent["cv_matches"]] == ["cv-chunk-1"]
    assert [h["id"] for h in sent["project_matches"]] == ["project-chunk-1"]
    assert set(deck["hits"]) == {"cv_1", "project_1"}
    assert deck["hits"]["cv_1"]["content"] == "Senior integration engineer"
    assert deck["tender_id"] == "tender-001"


def test_generate_uses_the_deck_timeout_for_proposal_only(client_generating, seen):
    client_generating.post("/api/proposal/tender-001", json={})
    timeouts = {r.url.path: r.extensions["timeout"]["read"] for r in seen}
    assert timeouts["/proposal/tender-001"] == 180
    assert timeouts["/tenders/tender-001"] == 30 and timeouts["/query"] == 30


def test_generate_accepts_an_absent_body(client_generating):
    assert client_generating.post("/api/proposal/tender-001").status_code == 200


def test_generate_forwards_settings_to_the_proposal_service(client_generating, seen):
    settings = {"day_rate": 700, "team_size": 3}
    assert client_generating.post("/api/proposal/tender-001",
                                  json={"settings": settings}).status_code == 200
    sent = json.loads(next(r for r in seen if r.url.path == "/proposal/tender-001").content)
    assert sent["settings"] == settings
    assert set(sent) == {"cv_matches", "project_matches", "settings"}


def test_generate_refuses_settings_that_are_not_an_object(client_generating, seen):
    for settings in ("700", 700, [{"day_rate": 700}]):
        response = client_generating.post("/api/proposal/tender-001", json={"settings": settings})
        assert response.status_code == 422, settings
    assert seen == []


def test_generate_forwards_force_bid_and_claim_check(client_generating, seen):
    assert client_generating.post("/api/proposal/tender-001",
                                  json={"force_bid": True, "claim_check": False}).status_code == 200
    sent = json.loads(next(r for r in seen if r.url.path == "/proposal/tender-001").content)
    assert sent["force_bid"] is True and sent["claim_check"] is False
    assert set(sent) == {"cv_matches", "project_matches", "force_bid", "claim_check"}


def test_generate_sends_neither_flag_when_the_body_has_none(client_generating, seen):
    client_generating.post("/api/proposal/tender-001", json={})
    sent = json.loads(next(r for r in seen if r.url.path == "/proposal/tender-001").content)
    assert "force_bid" not in sent and "claim_check" not in sent


def test_generate_refuses_flags_that_are_not_booleans(client_generating, seen):
    for field in ("force_bid", "claim_check"):
        for value in ("true", 1, "yes", None, []):
            response = client_generating.post("/api/proposal/tender-001", json={field: value})
            assert response.status_code == 422, (field, value)
    assert seen == []


def test_generate_refuses_unknown_body_fields(client_generating, seen):
    response = client_generating.post("/api/proposal/tender-001", json={"bid_anyway": True})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TENDER_INVALID_FIELD"
    assert seen == []


def test_generate_rejects_an_unsafe_id_without_calling_upstream(client, seen):
    response = client.post("/api/proposal/Lot%203", json={})
    assert response.status_code == 400
    assert seen == []


def test_generate_propagates_a_missing_tender(client_without_tender, seen):
    response = client_without_tender.post("/api/proposal/tender-001", json={})
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
    assert [r.url.path for r in seen] == ["/tenders/tender-001"]


def _chunk(chunk_id, content, record):
    return {"id": chunk_id, "content": content, "metadata": {"record_id": record}}


def test_hits_keep_the_first_chunk_of_a_record():
    best, worse = _chunk("c1", "best", "cv_1"), _chunk("c2", "worse", "cv_1")
    assert hits_by_record([best, worse])["cv_1"]["content"] == "best"


def test_hits_keep_the_cv_hit_when_a_record_is_in_both_lists():
    cv, project = _chunk("c1", "from cv", "shared"), _chunk("p1", "from project", "shared")
    assert hits_by_record([cv], [project])["shared"]["content"] == "from cv"
