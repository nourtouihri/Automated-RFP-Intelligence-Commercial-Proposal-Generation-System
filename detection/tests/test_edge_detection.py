"""Edge-case matrix from phase-2 §4.2 — one test per row.

The contract these pin down: every ingest ends in accept, accept-with-flags
(`quality.warnings` non-empty / status `incomplete`), or reject-with-envelope
(422 + machine-readable code). Nothing 500s, nothing sanitizes silently, and
the LLM is never consulted for records that carry no text to analyze.
"""

import json
import os
import sqlite3
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

from shared import store
from shared.dedup import canonical_key
from shared.errors import ApiError, ErrorCode, install
from detection.main import app
from detection.normalize import (
    RAW_TEXT_MAX_CHARS,
    REQUIREMENT_MAX_CHARS,
    REQUIREMENTS_MAX_ITEMS,
    clean_untrusted_text,
    normalize_tender,
    prepare_payload,
)

TOKEN_HEADER = {"X-Internal-Token": "test-token"}

BASE = {
    "title": "MuleSoft Integration Across HR Systems",
    "issuer": "ACME Group",
    "deadline": "2026-12-01",
    "raw_text": "Deliver a MuleSoft integration layer unifying our HR and payroll systems.",
    "requirements": ["MuleSoft integration layer", "Versioned API handover"],
    "source": "simulated_feed",
}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.init_db()
    yield


def _llm_must_not_be_called():
    """Fail loudly if a path that should be LLM-free reaches the transport."""
    return patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("LLM must not be called on this path"),
    )


# --- Row 1: missing deadline -------------------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_missing_deadline_incomplete():
    with _llm_must_not_be_called():
        tender, is_existing = await normalize_tender({**BASE, "deadline": None})
    assert not is_existing
    assert tender.deadline is None
    assert tender.status == "incomplete"
    assert "missing_deadline" in tender.quality.warnings
    assert "deadline" in tender.quality.missing_fields


# --- Row 2: deadline as datetime or dd/mm/yyyy -------------------------------

@pytest.mark.asyncio
async def test_edge_detection_deadline_iso_datetime():
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender({**BASE, "deadline": "2026-12-01T14:30:00Z"})
    assert tender.deadline == date(2026, 12, 1)
    assert "deadline_day_first" not in tender.quality.warnings


@pytest.mark.asyncio
async def test_edge_detection_deadline_dd_mm_yyyy_day_first():
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender({**BASE, "deadline": "01/12/2026"})
    assert tender.deadline == date(2026, 12, 1)
    assert "deadline_day_first" in tender.quality.warnings


@pytest.mark.asyncio
async def test_edge_detection_deadline_forms_rejected():
    """Compact (20261120) and week-date (2026-W47-5) forms must never win."""
    for bad in ("20261120", "2026-W47-5"):
        with pytest.raises(ApiError) as excinfo:
            prepare_payload({**BASE, "deadline": bad})
        assert excinfo.value.code == ErrorCode.TENDER_INVALID_DEADLINE
        assert excinfo.value.field == "deadline"


# --- Row 3: deadline in the past ---------------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_deadline_in_past_is_expired():
    past = date.today() - timedelta(days=1)
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender({**BASE, "deadline": past.isoformat()})
    assert tender.deadline == past
    assert tender.quality.is_expired is True
    assert "deadline_in_past" in tender.quality.warnings


# --- Row 4: no raw_text but has requirements ----------------------------------

@pytest.mark.asyncio
async def test_edge_detection_no_raw_text_with_requirements():
    payload = {key: value for key, value in BASE.items() if key != "raw_text"}
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender(payload)
    assert tender.raw_text == ""
    assert tender.requirements == BASE["requirements"]
    assert "no_raw_text" in tender.quality.warnings
    assert tender.status == "incomplete"


# --- Row 5: only title + issuer ----------------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_title_issuer_only_incomplete_no_llm():
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender(
            {"title": "Supply of Office Furniture", "issuer": "ACME Group"}
        )
    assert tender.status == "incomplete"
    assert tender.quality.completeness < 0.4
    assert tender.requirements == []
    assert tender.sector == "unknown"


# --- Row 6: empty / whitespace / null required field --------------------------

@pytest.mark.asyncio
async def test_edge_detection_empty_required_field_422_envelope():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for field in ("title", "issuer"):
            for blank in ("", "   ", None):
                payload = {**BASE, field: blank}
                resp = await client.post(
                    "/tenders/ingest", json=payload, headers=TOKEN_HEADER
                )
                assert resp.status_code == 422, (field, blank)
                body = resp.json()
                assert "detail" not in body  # never FastAPI's default shape
                error = body["error"]
                assert error["code"] == "TENDER_INVALID_FIELD"
                assert error["field"] == field
                assert error["retryable"] is False
                assert error["request_id"]
                assert resp.headers["X-Request-ID"] == error["request_id"]


# --- Row 7: HTML, NUL, zero-width, bidi ---------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_sanitized_html_nul_zero_width_bidi():
    dirty = (
        "<p>Deliver <b>MuleSoft</b> integration.</p>"
        "<script>alert('xss')</script>"
        "NUL:\u0000 zero:\u200b bidi:\u202e soft:\u00ad"
    )
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender({**BASE, "raw_text": dirty})

    assert "sanitized_chars" in tender.quality.warnings
    assert "alert" not in tender.raw_text  # <script> body dropped
    assert "<p>" not in tender.raw_text and "<b>" not in tender.raw_text
    for invisible in ("\u0000", "\u200b", "\u202e", "\u00ad"):
        assert invisible not in tender.raw_text
    assert "Deliver MuleSoft integration." in tender.raw_text
    assert "NUL:" in tender.raw_text  # text around the stripped chars survives

    # Legitimate Arabic/RTL prose passes through byte-identical.
    arabic = "عقد صيانة وتطوير منصة البيانات"
    cleaned, changed = clean_untrusted_text(arabic)
    assert cleaned == arabic and changed is False

    # French typography: NBSP folds to a plain space (a reported change).
    assert clean_untrusted_text("Réglementation\u00a0n°2") == ("Réglementation n°2", True)


# --- Row 8: raw_text over the cap ---------------------------------------------

def test_edge_detection_raw_text_over_cap_422():
    with pytest.raises(ApiError) as excinfo:
        prepare_payload({**BASE, "raw_text": "x" * (RAW_TEXT_MAX_CHARS + 1)})
    assert excinfo.value.code == ErrorCode.RAW_TEXT_TOO_LONG
    assert excinfo.value.field == "raw_text"
    assert excinfo.value.status_code == 422
    assert excinfo.value.retryable is False


# --- Row 9: accent / punctuation / legal-suffix variants ----------------------

@pytest.mark.asyncio
async def test_edge_detection_dedup_accent_punct_legal_suffix_same_key():
    assert canonical_key("Modernisation du SI — réseau", "Société Générale SA") == (
        canonical_key("modernisation du SI - reseau!", "Societe Generale")
    )
    # Different lots must NOT collapse into one key.
    assert canonical_key("Supply Lot 1", "ACME") != canonical_key("Supply Lot 2", "ACME")

    variant_a = {
        **BASE,
        "title": "Modernisation du SI — réseau",
        "issuer": "Société Générale SA",
    }
    variant_b = {
        **BASE,
        "title": "Modernisation du SI - reseau!",
        "issuer": "Societe Generale",
    }
    with _llm_must_not_be_called():
        first, first_existing = await normalize_tender(variant_a)
        second, second_existing = await normalize_tender(variant_b)
    assert not first_existing
    assert second_existing is True  # same dedup key -> same row, no duplicate
    assert second.id == first.id
    assert len(store.list_tenders()) == 1


# --- Row 10: near-duplicate warning, never merged -----------------------------

@pytest.mark.asyncio
async def test_edge_detection_near_duplicate_warns_never_merges():
    first_payload = {
        **BASE,
        "title": "Supply of Laptops for Field Staff",
        "raw_text": "Deliver a MuleSoft integration layer for asset tracking systems.",
    }
    second_payload = {
        **BASE,
        "title": "Supply of Laptops for Field Staff (Lot 2)",
        "raw_text": "Deliver a MuleSoft integration layer for asset tracking systems.",
    }
    with _llm_must_not_be_called():
        first, _ = await normalize_tender(first_payload)
        second, second_existing = await normalize_tender(second_payload)

    assert second_existing is False  # a different lot is a different row
    assert second.id != first.id
    assert len(store.list_tenders()) == 2
    assert f"possible_duplicate_of:{first.id}" in second.quality.warnings


# --- Row 11: wrong types -------------------------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_wrong_types_422():
    with pytest.raises(ApiError) as requirements_case:
        prepare_payload({**BASE, "requirements": "not-a-list"})
    assert requirements_case.value.code == ErrorCode.TENDER_INVALID_REQUIREMENTS
    assert requirements_case.value.field == "requirements"

    with pytest.raises(ApiError) as deadline_case:
        prepare_payload({**BASE, "deadline": 20261201})
    assert deadline_case.value.code == ErrorCode.TENDER_INVALID_DEADLINE

    with pytest.raises(ApiError) as title_case:
        prepare_payload({**BASE, "title": 123})
    assert title_case.value.code == ErrorCode.TENDER_INVALID_FIELD

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/tenders/ingest",
            json={**BASE, "deadline": 20261201},
            headers=TOKEN_HEADER,
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TENDER_INVALID_DEADLINE"


# --- Row 12: unknown extra fields ---------------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_unknown_fields_ignored_warned():
    payload = {**BASE, "priority": "urgent", "lot_number": 7}
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender(payload)
    assert "unknown_fields" in tender.quality.warnings
    assert tender.status == "new"  # ignored, not fatal


# --- Row 13: LLM down / bad key / garbage -------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_llm_down_or_garbage_never_500():
    def payload(title):
        # Keyphrased title keeps sector tagging deterministic, so the only
        # LLM call in play is requirement extraction.
        return {**BASE, "title": title, "requirements": None}

    for index, side_effect in enumerate(
        (httpx.ConnectError("provider down"), ValueError("missing API key"))
    ):
        with patch("detection.normalize.llm_call", new_callable=AsyncMock, side_effect=side_effect):
            tender, _ = await normalize_tender(
                payload(f"Integration Platform Upgrade Phase {index}")
            )
        assert "llm_unavailable" in tender.quality.warnings
        assert tender.requirements  # deterministic fallback, not empty
        assert tender.status == "new"

    # Garbage output is salvaged line-by-line, flagged, and accepted.
    with patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        return_value="I cannot help with that.",
    ):
        tender, _ = await normalize_tender(payload("Integration Platform Upgrade Garbage"))
    assert "llm_unavailable" in tender.quality.warnings
    assert tender.requirements == ["I cannot help with that."]

    # End-to-end: garbage degraded ingest is a 200 with warnings, never a 500.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "detection.normalize.llm_call",
            new_callable=AsyncMock,
            return_value="total garbage",
        ):
            resp = await client.post(
                "/tenders/ingest",
                json=payload("Integration Platform Upgrade API Garbage"),
                headers=TOKEN_HEADER,
            )
    assert resp.status_code == 200
    assert "llm_unavailable" in resp.json()["quality"]["warnings"]


# --- Row 14: requirement caps --------------------------------------------------

def test_edge_detection_requirements_supplied_caps_rejected():
    with pytest.raises(ApiError) as long_item:
        prepare_payload({**BASE, "requirements": ["x" * (REQUIREMENT_MAX_CHARS + 1)]})
    assert long_item.value.code == ErrorCode.TENDER_INVALID_REQUIREMENTS

    with pytest.raises(ApiError) as too_many:
        prepare_payload(
            {**BASE, "requirements": [f"req {i}" for i in range(REQUIREMENTS_MAX_ITEMS + 1)]}
        )
    assert too_many.value.code == ErrorCode.TENDER_INVALID_REQUIREMENTS


@pytest.mark.asyncio
async def test_edge_detection_requirements_llm_produced_trimmed_and_capped():
    llm_payload = [f"Requirement number {index}" for index in range(REQUIREMENTS_MAX_ITEMS + 5)]
    llm_payload.append("A" * (REQUIREMENT_MAX_CHARS + 200))
    with patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        return_value=json.dumps(llm_payload),
    ):
        tender, _ = await normalize_tender(
            {**BASE, "title": "Integration Platform Upgrade Caps", "requirements": None}
        )
    assert len(tender.requirements) == REQUIREMENTS_MAX_ITEMS
    assert all(len(item) <= REQUIREMENT_MAX_CHARS for item in tender.requirements)
    assert "requirements_trimmed" in tender.quality.warnings
    assert "requirements_capped" in tender.quality.warnings


# --- Request id propagation -----------------------------------------------------

@pytest.mark.asyncio
async def test_edge_detection_request_id_echo_and_replace():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad_payload = {**BASE, "title": ""}

        resp = await client.post(
            "/tenders/ingest",
            json=bad_payload,
            headers={**TOKEN_HEADER, "X-Request-ID": "run-42.abc_1"},
        )
        assert resp.headers["X-Request-ID"] == "run-42.abc_1"
        assert resp.json()["error"]["request_id"] == "run-42.abc_1"

        for evil in ("a" * 80, "bad id!!"):
            resp = await client.post(
                "/tenders/ingest",
                json=bad_payload,
                headers={**TOKEN_HEADER, "X-Request-ID": evil},
            )
            generated = resp.headers["X-Request-ID"]
            assert generated != evil  # never reflected verbatim
            assert "<" not in generated and " " not in generated
            assert resp.json()["error"]["request_id"] == generated

        # Success responses carry the header too.
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.headers["X-Request-ID"]


# --- 4.1 contract: unhandled errors are envelopes, not raw 500s ----------------

def test_edge_detection_validation_error_alias_is_envelope_backed():
    from detection.normalize import ValidationError as NormalizeValidationError

    assert NormalizeValidationError is ApiError


@pytest.mark.asyncio
async def test_edge_detection_unhandled_error_becomes_envelope():
    boom_app = FastAPI()
    install(boom_app)

    @boom_app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=boom_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/boom", headers={"X-Request-ID": "run-500.abc"})

    assert resp.status_code == 500
    assert "detail" not in resp.json()
    error = resp.json()["error"]
    assert error["code"] == "INTERNAL"
    assert error["retryable"] is True
    # The id survives even though the 500 is rendered outside the middleware.
    assert error["request_id"] == "run-500.abc"
    assert resp.headers["X-Request-ID"] == "run-500.abc"


@pytest.mark.asyncio
async def test_edge_detection_not_found_envelope():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/tenders/does-not-exist", headers=TOKEN_HEADER)
    assert resp.status_code == 404
    assert "detail" not in resp.json()
    error = resp.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["retryable"] is False
    assert error["request_id"]


# --- Migration: v0 DB -> v2, research intact, no duplicate on re-ingest --------

def _build_legacy_db(db_path):
    """Hand-build the pre-v2 schema (deadline NOT NULL, no quality columns)."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE tenders (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            issuer TEXT NOT NULL,
            sector TEXT NOT NULL,
            requirements TEXT NOT NULL,
            deadline TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            source TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            status TEXT NOT NULL,
            dedup_hash TEXT UNIQUE
        );
        CREATE TABLE research (
            tender_id TEXT PRIMARY KEY REFERENCES tenders(id) ON DELETE CASCADE,
            issuer TEXT NOT NULL DEFAULT '',
            sector TEXT,
            estimated_revenue TEXT,
            past_projects TEXT NOT NULL,
            key_partners TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL,
            sources TEXT NOT NULL,
            status TEXT,
            completed_at TEXT
        );
        INSERT INTO tenders VALUES (
            't-1', 'Modernisation du SI — réseau', 'Société Générale SA',
            'Data Integration', '["Integration layer"]', '2026-12-01',
            'mulesoft migration work', 'simulated_feed',
            '2026-10-01T10:00:00+00:00', 'new', 'deadbeefdeadbeef'
        );
        INSERT INTO research VALUES (
            't-1', 'Société Générale SA', 'Banking', '120m EUR',
            '["Core banking modernisation"]', '["Regional SI vendor"]',
            'Legacy note.', 'medium', '["https://example.com/report"]',
            'complete', NULL
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_edge_detection_migration_v0_backfills_and_rehashes(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _build_legacy_db(db_path)
    monkeypatch.setattr(store, "DB_PATH", db_path)

    store.init_db()

    # The rebuild must not cascade-delete research attached to tenders.
    research = store.get_research("t-1")
    assert research is not None
    assert research.issuer == "Société Générale SA"

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        stored_hash = conn.execute(
            "SELECT dedup_hash FROM tenders WHERE id = 't-1'"
        ).fetchone()[0]
    assert version == 2
    # The stored v1 hash was recomputed with the v2 canonicalization.
    assert stored_hash == canonical_key("Modernisation du SI — réseau", "Société Générale SA")

    # Re-ingesting a v1-era variant must land on the migrated row, not duplicate it.
    with _llm_must_not_be_called():
        tender, is_existing = await normalize_tender(
            {
                "title": "modernisation du SI - reseau!",
                "issuer": "Societe Generale",
                "deadline": "2026-12-01",
                "raw_text": "mulesoft integration layer and versioned API handover",
                "requirements": ["Integration layer"],
            }
        )
    assert is_existing is True
    assert tender.id == "t-1"
    assert len(store.list_tenders()) == 1


# --- Sparse re-trigger: an incomplete payload must not downgrade a record -----


@pytest.mark.asyncio
async def test_edge_detection_sparse_reingest_preserves_record_and_research():
    """A title+issuer re-trigger (n8n re-reads the sheet row) must not wipe the
    stored raw_text/requirements, flip status to `incomplete`, or delete the
    derived research. Before the merge fix, requirements became [] and the
    research row was cascade-deleted.
    """
    from datetime import datetime, timezone

    from shared.schemas import ProspectResearch

    with _llm_must_not_be_called():
        first, first_existing = await normalize_tender(BASE)
    assert not first_existing
    assert first.requirements == BASE["requirements"]

    store.save_research(
        first.id,
        ProspectResearch(
            tender_id=first.id,
            issuer=first.issuer,
            sector="Data Integration",
            estimated_revenue="$10M",
            past_projects=["a"],
            key_partners=["b"],
            notes="n",
            confidence="high",
            sources=["https://example.com"],
            status="complete",
            completed_at=datetime.now(timezone.utc),
        ),
    )

    with _llm_must_not_be_called():
        second, second_existing = await normalize_tender(
            {"title": BASE["title"], "issuer": BASE["issuer"]}
        )

    assert second_existing is True
    assert second.id == first.id
    assert second.requirements == BASE["requirements"]
    assert second.raw_text == BASE["raw_text"]
    assert second.deadline == date(2026, 12, 1)
    assert second.status == "new"
    assert second.quality.completeness == 1.0
    assert store.get_research(first.id) is not None


@pytest.mark.asyncio
async def test_edge_detection_sparse_reingest_with_new_deadline_keeps_requirements():
    """A sparse re-trigger that also carries a new deadline must refresh the
    deadline but keep the stored requirements/raw_text and reuse the stored
    sector — without re-spending the LLM.
    """
    with _llm_must_not_be_called():
        first, _ = await normalize_tender(BASE)

    with _llm_must_not_be_called():
        second, second_existing = await normalize_tender(
            {
                "title": BASE["title"],
                "issuer": BASE["issuer"],
                "deadline": "2027-01-15",
            }
        )

    assert second_existing is True
    assert second.id == first.id
    assert second.deadline == date(2027, 1, 15)
    assert second.requirements == BASE["requirements"]
    assert second.raw_text == BASE["raw_text"]
    assert second.status == "new"


@pytest.mark.asyncio
async def test_edge_detection_reenrich_fills_missing_deadline():
    """A later, richer trigger must upgrade a previously incomplete record."""
    detail = {
        "title": "Payroll Data Platform",
        "issuer": "Beta Corp",
        "raw_text": "Build a Snowflake data platform for payroll analytics reporting.",
        "requirements": ["Snowflake warehouse", "dbt models"],
    }
    with _llm_must_not_be_called():
        first, _ = await normalize_tender(detail)
    assert first.status == "incomplete"
    assert "deadline" in first.quality.missing_fields

    with _llm_must_not_be_called():
        second, second_existing = await normalize_tender(
            {
                "title": "Payroll Data Platform",
                "issuer": "Beta Corp",
                "deadline": "2027-03-01",
            }
        )

    assert second_existing is True
    assert second.deadline == date(2027, 3, 1)
    assert second.requirements == detail["requirements"]
    assert second.status == "new"
    assert "deadline" not in second.quality.missing_fields


@pytest.mark.asyncio
async def test_edge_detection_fresh_payload_without_text_stays_incomplete():
    """Guard against over-merging: a *new* title+issuer with no stored row is
    still an incomplete record, not silently enriched from anywhere."""
    with _llm_must_not_be_called():
        tender, is_existing = await normalize_tender(
            {"title": "Greenfield Tender", "issuer": "Gamma Ltd"}
        )
    assert is_existing is False
    assert tender.status == "incomplete"
    assert tender.requirements == []
    assert "raw_text" in tender.quality.missing_fields


# --- Lifecycle status survives re-ingest --------------------------------------


@pytest.mark.asyncio
async def test_edge_detection_material_revision_keeps_advanced_status():
    """n8n re-firing a sheet row must refresh the tender without resetting the
    lifecycle state it was advanced to: `processed`/`archived` survive."""
    with _llm_must_not_be_called():
        tender, _ = await normalize_tender(BASE)
    assert tender.status == "new"

    for advanced in ("processed", "archived"):
        with sqlite3.connect(store.DB_PATH) as conn:
            conn.execute(
                "UPDATE tenders SET status = ? WHERE id = ?", (advanced, tender.id)
            )
        with _llm_must_not_be_called():
            updated, is_existing = await normalize_tender(
                {
                    **BASE,
                    "raw_text": BASE["raw_text"] + f" Phase {advanced} scope added.",
                }
            )
        assert is_existing is True
        assert updated.id == tender.id
        assert updated.status == advanced
        assert store.get_tender(tender.id).status == advanced
