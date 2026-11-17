import json

import pytest
from fastapi.testclient import TestClient

from ingestion import main
from ingestion.USA import sam
from research.tools.fetch import FetchError

NOTICE = {
    "noticeId": "abc123",
    "title": "Cloud migration",
    "type": "Solicitation",
    "description": "https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid=abc123",
    "fullParentPathName": "DEPT OF DEFENSE",
    "officeAddress": {"countryCode": "USA"},
    "postedDate": "2026-10-01",
    "responseDeadLine": "2026-12-01T17:00:00-05:00",
}


def test_description_fetch_moves_query_into_params(monkeypatch):
    calls = []

    async def fake_fetch(url, method="GET", params=None, json_body=None, max_bytes=None):
        calls.append((url, params))
        return json.dumps({"description": "Description: Migrate the payroll system."})

    monkeypatch.setattr(sam, "fetch_url", fake_fetch)
    batch = sam.SamBatchResponse.model_validate({"totalRecords": 1, "opportunitiesData": [NOTICE]})
    mapped = sam.SamBatchMappingHandler(api_key="SAM-key").handle(batch)

    assert calls == [(
        "https://api.sam.gov/prod/opportunities/v1/noticedesc",
        {"noticeid": "abc123", "api_key": "SAM-key"},
    )]
    assert mapped.notices[0].raw_text == "Migrate the payroll system."


def test_upstream_fetch_failure_is_a_retryable_503(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "t")
    monkeypatch.setenv("INGEST_API_KEYS", "ted,SAM-key")

    def refused(self, page=1):
        raise FetchError("Fetch failed with status 429")

    monkeypatch.setattr(sam.SamBatchIngestionHandler, "run", refused)
    res = TestClient(main.app).post("/ingest/SAM", json={"page": 1}, headers={"X-Internal-Token": "t"})

    assert res.status_code == 503
    body = res.json()["error"]
    assert body["code"] == "UPSTREAM_UNAVAILABLE" and body["retryable"] is True
    assert "429" in body["message"]
