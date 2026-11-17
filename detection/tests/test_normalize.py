import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

from shared import store
from shared.errors import ApiError, ErrorCode
from detection.main import app
from detection.normalize import (
    RAW_TEXT_MAX_CHARS,
    SECTOR_KEYPHRASES,
    extract_json_payload,
    normalize_tender,
    prepare_payload,
    tag_sector,
)
from shared.schemas import CAPABILITY_TAXONOMY

VALID_DATA = {
    "title": "MuleSoft Integration Across HR Systems",
    "issuer": "ACME Group",
    "deadline": "2026-12-01",
    "raw_text": "Deliver a MuleSoft integration layer unifying our HR and payroll systems.",
    "requirements": ["MuleSoft integration layer", "Versioned API handover"],
    "source": "simulated_feed",
}
TOKEN_HEADER = {"X-Internal-Token": "test-token"}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Provides isolated SQLite database per test function."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.init_db()
    yield


# --- Upfront Field & Date Validation Tests ---

def test_missing_required_field():
    # Only title/issuer are hard-required now: a missing deadline or raw_text
    # degrades the record to `incomplete` instead of rejecting it (phase-2 §4.2).
    for field in ("title", "issuer"):
        data = {**VALID_DATA, field: ""}
        with pytest.raises(ApiError, match=f"Missing required field: {field}"):
            prepare_payload(data)


def test_whitespace_required_field():
    for field in ("title", "issuer"):
        data = {**VALID_DATA, field: "   "}
        with pytest.raises(ApiError, match=f"Missing required field: {field}"):
            prepare_payload(data)


def test_optional_fields_degrade_instead_of_rejecting():
    """Missing deadline/raw_text are flagged, not fatal (matrix rows 1, 4, 5)."""
    prepared = prepare_payload({k: v for k, v in VALID_DATA.items() if k not in ("deadline", "raw_text")})
    assert prepared.deadline is None
    assert prepared.raw_text == ""
    assert "missing_deadline" in prepared.warnings
    assert "no_raw_text" in prepared.warnings
    assert set(prepared.missing_fields) == {"deadline", "raw_text"}


def test_invalid_deadline_format():
    data = {**VALID_DATA, "deadline": "not-a-valid-date"}
    with pytest.raises(ApiError, match="Invalid deadline date format"):
        prepare_payload(data)


@pytest.mark.asyncio
async def test_invalid_date_rejects_upfront_without_llm():
    """Verifies malformed date rejects before executing any paid LLM calls."""
    data = {**VALID_DATA, "deadline": "invalid-date", "requirements": []}
    with patch("detection.normalize.llm_call", new_callable=AsyncMock) as mock_llm:
        with pytest.raises(ApiError, match="Invalid deadline date format"):
            await normalize_tender(data)
        assert mock_llm.call_count == 0


def test_raw_text_over_cap():
    data = {**VALID_DATA, "raw_text": "x" * (RAW_TEXT_MAX_CHARS + 1)}
    with pytest.raises(ApiError, match="exceeds") as excinfo:
        prepare_payload(data)
    assert excinfo.value.code == ErrorCode.RAW_TEXT_TOO_LONG
    assert excinfo.value.field == "raw_text"


def test_raw_text_at_cap_accepted():
    data = {**VALID_DATA, "raw_text": "x" * RAW_TEXT_MAX_CHARS}
    prepare_payload(data)


# --- Source Allowlist Tests ---

@pytest.mark.asyncio
async def test_sam_source_is_accepted():
    with patch("detection.normalize.llm_call", new_callable=AsyncMock):
        tender, _ = await normalize_tender({**VALID_DATA, "id": "sam-001", "source": "SAM"})
    assert tender.source == "SAM"


@pytest.mark.asyncio
async def test_unknown_source_names_every_allowed_value():
    with patch("detection.normalize.llm_call", new_callable=AsyncMock):
        with pytest.raises(ApiError) as e:
            await normalize_tender({**VALID_DATA, "source": "UAE"})
    assert e.value.field == "source" and "'SAM'" in e.value.message


# --- Idempotent Deduplication Tests ---

@pytest.mark.asyncio
async def test_duplicate_returns_existing_without_re_llm():
    """Verifies duplicate ingest returns existing record idempotently without re-spending LLM tokens."""
    with patch("detection.normalize.llm_call", new_callable=AsyncMock) as mock_llm:
        tender1, is_existing1 = await normalize_tender(VALID_DATA.copy())
        assert not is_existing1

        tender2, is_existing2 = await normalize_tender(VALID_DATA.copy())
        assert is_existing2
        assert tender2.id == tender1.id
        assert mock_llm.call_count == 0


# --- Sector Tagging Keyphrase & LLM Fallback Tests ---

def test_keyphrase_sector_match():
    assert (
        tag_sector("mulesoft integration with sap successfactors and payroll", "Global HRIS Integration")
        == "Data Integration"
    )
    assert (
        tag_sector("demand forecasting using machine learning on order history", "Forecasting")
        == "AI Development"
    )
    assert (
        tag_sector("power bi reporting layer with a semantic model and kpi definitions", "Analytics")
        == "BI & Dashboarding"
    )
    assert (
        tag_sector("salesforce service cloud case management rollout", "CRM Overhaul")
        == "Salesforce Ecosystem"
    )
    assert (
        tag_sector("kafka streaming into a databricks lakehouse", "Streaming")
        == "Data Platform"
    )


def test_keyphrase_sector_n8n_keyed_to_data_integration():
    """n8n is OliveSoft's certified-partner automation tool, so it must land on Data Integration."""
    assert (
        tag_sector("n8n workflow automation connecting erp to crm", "Automation")
        == "Data Integration"
    )


def test_keyphrase_sector_tie_break_follows_taxonomy_order():
    """Equal scores resolve to the earlier category in CAPABILITY_TAXONOMY, deterministically."""
    # One keyphrase from each of the two earliest lines, so the scores tie.
    tied_text = "mulesoft and machine learning"
    assert (
        tag_sector(tied_text, "Notice")
        == CAPABILITY_TAXONOMY[0]
    )
    # Repeat calls agree; the winner is a function of taxonomy order, not dict iteration luck.
    assert len({tag_sector(tied_text, "Notice") for _ in range(10)}) == 1


def test_sector_keyphrases_cover_exact_taxonomy():
    """Keyphrase map and taxonomy must not drift: the module-level guard enforces it at import."""
    assert set(SECTOR_KEYPHRASES) == set(CAPABILITY_TAXONOMY)
    assert CAPABILITY_TAXONOMY == [
        "Data Integration",
        "AI Development",
        "BI & Dashboarding",
        "Salesforce Ecosystem",
        "Data Platform",
    ]


def test_keyphrase_sector_no_match_returns_unknown():
    assert tag_sector("generic ambiguous text without keyphrases", "Notice") == "unknown"


# --- Markdown Fence Proof JSON Extraction Tests ---

def test_extract_json_payload_markdown_fences():
    fenced_input = '```json\n["Req A", "Req B"]\n```'
    assert extract_json_payload(fenced_input) == '["Req A", "Req B"]'

    preamble_input = 'Here are the requirements:\n```json\n["Req 1"]\n```'
    assert extract_json_payload(preamble_input) == '["Req 1"]'


# --- Authentication Security Tests ---

@pytest.mark.asyncio
async def test_missing_token_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/tenders")
        assert resp.status_code == 401
        error = resp.json()["error"]
        assert error["code"] == "UNAUTHORIZED"
        assert error["message"] == "Invalid or missing X-Internal-Token"
        assert error["retryable"] is False
        assert error["request_id"]
        assert resp.headers["X-Request-ID"] == error["request_id"]


@pytest.mark.asyncio
async def test_wrong_token_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/tenders", headers={"X-Internal-Token": "wrong-secret"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_works():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/tenders", headers=TOKEN_HEADER)
        assert resp.status_code == 200


# --- API Integration & Seed Tests ---

@pytest.mark.asyncio
async def test_ingest_endpoint():
    with patch("detection.normalize.llm_call", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/tenders/ingest", json=VALID_DATA, headers=TOKEN_HEADER)
            assert resp.status_code == 200
            body = resp.json()
            assert body["title"] == "MuleSoft Integration Across HR Systems"
            assert body["issuer"] == "ACME Group"
            assert body["sector"] == "Data Integration"


@pytest.mark.asyncio
async def test_ingest_invalid_date_returns_422():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad_data = {**VALID_DATA, "deadline": "2026-99-99"}
        resp = await client.post("/tenders/ingest", json=bad_data, headers=TOKEN_HEADER)
        assert resp.status_code == 422


async def _ingest(client, data=VALID_DATA):
    with patch("detection.normalize.llm_call", new_callable=AsyncMock):
        resp = await client.post("/tenders/ingest", json=data, headers=TOKEN_HEADER)
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_archive_then_restore():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tender_id = await _ingest(client)
        url = f"/tenders/{tender_id}/status"
        r = await client.patch(url, json={"status": "archived"}, headers=TOKEN_HEADER)
        assert r.status_code == 200 and r.json()["status"] == "archived"
        r = await client.patch(url, json={"status": "active"}, headers=TOKEN_HEADER)
        assert r.json()["status"] == "new"


@pytest.mark.asyncio
async def test_restore_derives_incomplete_when_fields_are_missing():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sparse = {k: v for k, v in VALID_DATA.items() if k not in ("deadline", "raw_text")}
        tender_id = await _ingest(client, sparse)
        url = f"/tenders/{tender_id}/status"
        await client.patch(url, json={"status": "archived"}, headers=TOKEN_HEADER)
        r = await client.patch(url, json={"status": "active"}, headers=TOKEN_HEADER)
        assert r.json()["status"] == "incomplete"


@pytest.mark.asyncio
async def test_archive_unknown_tender_is_404_envelope():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.patch("/tenders/nope/status", json={"status": "archived"}, headers=TOKEN_HEADER)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"status": "processed"}, {"status": "bogus"}, {}])
async def test_status_refuses_values_other_than_archived_and_active(body):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tender_id = await _ingest(client)
        r = await client.patch(f"/tenders/{tender_id}/status", json=body, headers=TOKEN_HEADER)
        assert r.status_code == 422
        assert r.json()["error"]["field"] == "body.status"
        assert store.get_tender(tender_id).status == "new"


@pytest.mark.asyncio
async def test_status_requires_the_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.patch("/tenders/x/status", json={"status": "archived"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_reingest_keeps_archived():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tender_id = await _ingest(client)
        await client.patch(f"/tenders/{tender_id}/status", json={"status": "archived"}, headers=TOKEN_HEADER)
        assert await _ingest(client) == tender_id
        assert store.get_tender(tender_id).status == "archived"


@pytest.mark.asyncio
async def test_seed_tenders_endpoint():
    with patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        return_value="Data Integration",
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/tenders/seed", headers=TOKEN_HEADER)
            assert resp.status_code == 200
            body = resp.json()
            assert body["seeded"] >= 15
            assert all(t["status"] == "success" for t in body["tenders"])


@pytest.mark.asyncio
async def test_seed_feed_reports_dedupe_on_repost():
    """The feed ships a re-announced tender; seeding twice must not create a second row."""
    with patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        return_value="Data Integration",
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/tenders/seed", headers=TOKEN_HEADER)
            second = await client.post("/tenders/seed", headers=TOKEN_HEADER)
            assert first.status_code == second.status_code == 200

            before = len((await client.get("/tenders", headers=TOKEN_HEADER)).json())
            after = len((await client.get("/tenders", headers=TOKEN_HEADER)).json())
            assert before == after

            repost = next(t for t in second.json()["tenders"] if t["file"] == "tender_015.json")
            assert repost["existing"] is True


@pytest.mark.asyncio
async def test_seed_feed_exercises_requirement_extraction_fallback():
    """tender_013 ships no requirements[] key, so the LLM extraction path must fill it."""
    with patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        return_value='["Integrate telematics with maintenance and fuel systems"]',
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/tenders/seed", headers=TOKEN_HEADER)
            assert resp.status_code == 200
            extracted = next(
                t for t in resp.json()["tenders"] if t["file"] == "tender_013.json"
            )
            assert extracted["status"] == "success"

            tender = (await client.get(
                f"/tenders/{extracted['id']}", headers=TOKEN_HEADER
            )).json()
            assert tender["requirements"] == [
                "Integrate telematics with maintenance and fuel systems"
            ]


@pytest.mark.asyncio
async def test_seed_feed_sector_fallback_only_for_unclassifiable_tender():
    """Only tender_014 should miss the keyphrase pass and reach the LLM classifier."""
    with patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        return_value="Data Integration",
    ) as mock_llm:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/tenders/seed", headers=TOKEN_HEADER)
            assert resp.status_code == 200

            unclassifiable = next(
                t for t in resp.json()["tenders"] if t["file"] == "tender_014.json"
            )
            assert unclassifiable["status"] == "success"
            # Keyphrase tagging returns "unknown" for this one, so the payload
            # carried no sector and only the LLM fallback can fill it in.
            classified = (await client.get(
                f"/tenders/{unclassifiable['id']}", headers=TOKEN_HEADER
            )).json()
            assert classified["sector"] == "Data Integration"

            # Exactly two paid calls for the whole feed: the classifier for
            # tender_014, and requirement extraction for requirements-less
            # tender_013. Every other file is handled deterministically.
            assert mock_llm.call_count == 2


# --- Notice details (S8) ---

async def test_notice_details_are_kept():
    t, _ = await normalize_tender({**VALID_DATA, "id": "ted-1", "issuer_country": "FRA", "notice_type": "cn-standard",
                                   "published_at": "2026-10-22", "links": {"pdfs": {"ENG": "https://ted.example/a.pdf"}}})
    assert (t.issuer_country, t.notice_type, t.links) == ("FRA", "cn-standard", ["https://ted.example/a.pdf"])
    assert t.published_at.isoformat() == "2026-10-22"
    assert "unknown_fields" not in t.quality.warnings
    assert store.get_tender("ted-1").links == ["https://ted.example/a.pdf"]


async def test_unsafe_links_are_dropped():
    t, _ = await normalize_tender({**VALID_DATA, "id": "x", "links": ["javascript:alert(1)", "https://ok.example"]})
    assert t.links == ["https://ok.example"] and "links_trimmed" in t.quality.warnings


async def test_ted_links_are_flattened_pdfs_first_and_deduplicated():
    links = {"html": {"ENG": "https://ted.example/a.html", "FRA": "https://ted.example/a.pdf"},
             "pdfs": {"ENG": "https://ted.example/a.pdf"}}
    t, _ = await normalize_tender({**VALID_DATA, "id": "x", "links": links})
    assert t.links == ["https://ted.example/a.pdf", "https://ted.example/a.html"]
    assert "links_trimmed" not in t.quality.warnings


async def test_links_are_capped_in_count_and_length():
    urls = [f"https://ok.example/{i}" for i in range(25)] + ["https://ok.example/" + "x" * 2000]
    t, _ = await normalize_tender({**VALID_DATA, "id": "x", "links": urls})
    assert len(t.links) == 20 and "links_trimmed" in t.quality.warnings


async def test_notice_strings_are_cleaned_and_capped():
    t, _ = await normalize_tender({**VALID_DATA, "id": "x", "issuer_country": "<b>FR</b>A", "notice_type": "n" * 150})
    assert t.issuer_country == "FRA" and len(t.notice_type) == 100


async def test_unparseable_published_at_is_dropped_with_a_warning():
    t, _ = await normalize_tender({**VALID_DATA, "id": "x", "published_at": "last week"})
    assert t.published_at is None and "invalid_published_at" in t.quality.warnings


async def test_retrigger_that_omits_notice_details_keeps_them():
    await normalize_tender({**VALID_DATA, "id": "x", "issuer_country": "FRA", "notice_type": "cn", "published_at": "2026-10-22",
                            "links": ["https://ok.example"]})
    t, _ = await normalize_tender({**VALID_DATA, "id": "x", "deadline": "2026-12-15"})
    assert (t.issuer_country, t.notice_type, t.links) == ("FRA", "cn", ["https://ok.example"])
    assert t.published_at.isoformat() == "2026-10-22"
    assert store.get_tender("x").issuer_country == "FRA"


async def test_retrigger_that_changes_only_notice_details_updates_them():
    await normalize_tender({**VALID_DATA, "id": "x", "issuer_country": "FRA"})
    t, existing = await normalize_tender({**VALID_DATA, "id": "x", "issuer_country": "DEU", "links": ["https://ok.example"]})
    assert existing and t.issuer_country == "DEU" and t.links == ["https://ok.example"]
    assert store.get_tender("x").issuer_country == "DEU"


async def test_retrigger_with_empty_notice_details_keeps_stored_values():
    await normalize_tender({**VALID_DATA, "id": "x", "issuer_country": "FRA", "links": ["https://ok.example"]})
    t, _ = await normalize_tender({**VALID_DATA, "id": "x", "issuer_country": "  ", "links": []})
    assert t.issuer_country == "FRA" and t.links == ["https://ok.example"]


async def test_a_tender_id_with_slashes_is_reachable_by_get_and_status_change():
    tender_id = "Lot 3 / North"
    quoted = "Lot%203%20%2F%20North"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        made = await client.post("/tenders/ingest", json={**VALID_DATA, "id": tender_id}, headers=TOKEN_HEADER)
        assert made.json()["id"] == tender_id

        got = await client.get(f"/tenders/{quoted}", headers=TOKEN_HEADER)
        assert got.status_code == 200 and got.json()["id"] == tender_id

        archived = await client.patch(f"/tenders/{quoted}/status", json={"status": "archived"}, headers=TOKEN_HEADER)
        assert archived.status_code == 200 and archived.json()["status"] == "archived"

        listed = await client.get("/tenders", headers=TOKEN_HEADER)
        assert listed.status_code == 200 and [t["id"] for t in listed.json()] == [tender_id]
        assert (await client.get("/tenders/nope", headers=TOKEN_HEADER)).status_code == 404
