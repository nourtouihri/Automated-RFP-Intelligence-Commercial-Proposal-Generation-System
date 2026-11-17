"""Storage-layer idempotency.

AGENTS.md requires duplicate ingests to be handled idempotently because n8n
fires triggers more than once. This pins the guarantee at both layers it is
supposed to hold: the application-level hash short-circuit, and the UNIQUE
constraint underneath it.
"""

import pytest

from shared import store
from shared.schemas import ProspectResearch, Tender


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init_db()
    yield


def _tender(tender_id="t-1", title="Rail Signaling", issuer="MetroDOT", status="new"):
    from datetime import date, datetime, timezone

    return Tender(
        id=tender_id,
        title=title,
        issuer=issuer,
        sector="Security Assessment & Penetration Testing",
        requirements=["OWASP top 10 testing"],
        deadline=date(2026, 12, 1),
        raw_text="Procurement notice for rail signaling security review.",
        source="simulated_feed",
        detected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        status=status,
    )


def test_dedup_hash_is_stable_for_the_same_title_and_issuer():
    from detection.normalize import compute_dedup_hash

    a = compute_dedup_hash("Rail Signaling", "MetroDOT")
    b = compute_dedup_hash("Rail Signaling", "MetroDOT")
    assert a == b


def test_dedup_hash_differs_across_issuers_and_titles():
    from detection.normalize import compute_dedup_hash

    base = compute_dedup_hash("Rail Signaling", "MetroDOT")
    assert base != compute_dedup_hash("Rail Signaling", "OtherDOT")
    assert base != compute_dedup_hash("Road Works", "MetroDOT")


def test_find_by_hash_round_trips_a_saved_tender():
    store.save_tender(_tender(), "hash-1")
    found = store.find_by_hash("hash-1")
    assert found is not None
    assert found.id == "t-1"
    assert found.requirements == ["OWASP top 10 testing"], "JSON column must decode"


def test_find_by_hash_returns_none_for_unknown_hash():
    assert store.find_by_hash("never-seen") is None


def _research(tender_id="t-1", notes="precious"):
    return ProspectResearch(
        tender_id=tender_id, issuer="MetroDOT", sector="Transit",
        estimated_revenue="$1.2B", past_projects=["Signaling"],
        key_partners=["Stellar Civil"], notes=notes, confidence="medium",
        sources=["https://mdot.example"],
    )


def test_resaving_the_same_tender_updates_in_place_without_duplicating():
    """A re-ingest of the same id is an update, not a second row."""
    store.save_tender(_tender(status="new"), "hash-1")
    store.save_tender(_tender(status="processed"), "hash-1")
    assert len(store.list_tenders()) == 1
    assert store.get_tender("t-1").status == "processed"


# --- Re-ingest must never destroy research -------------------------------
# research.tender_id is ON DELETE CASCADE, so any statement that deletes and
# reinserts the tender row silently takes the computed research with it. These
# tests exist because `INSERT OR REPLACE` did exactly that on every re-ingest,
# and the tender row still looked correct, so the loss was invisible.

def test_resaving_a_tender_preserves_its_research():
    """The core regression: a status transition must not wipe research."""
    store.save_tender(_tender(status="new"), "hash-1")
    store.save_research("t-1", _research())

    store.save_tender(_tender(status="processed"), "hash-1")

    assert store.get_tender("t-1").status == "processed"
    kept = store.get_research("t-1")
    assert kept is not None, "re-saving a tender destroyed its research"
    assert kept.key_partners == ["Stellar Civil"]
    assert kept.confidence == "medium"


def test_duplicate_ingest_with_a_new_id_keeps_the_original_id_and_research():
    """Each ingest mints a random uuid, so a duplicate arrives under a new id.

    The first id must win, otherwise research already keyed to it is orphaned
    and a second row would appear for one document.
    """
    store.save_tender(_tender(tender_id="t-original"), "hash-1")
    store.save_research("t-original", _research("t-original"))

    store.save_tender(_tender(tender_id="t-duplicate"), "hash-1")

    assert store.get_tender("t-original") is not None
    assert store.get_tender("t-duplicate") is None, "duplicate created a second row"
    assert len(store.list_tenders()) == 1
    assert store.get_research("t-original") is not None


def test_edited_tender_with_same_id_refreshes_hash_and_keeps_research():
    """A sheet edit changes title -> new hash, same id. Must not 500 or lose data."""
    store.save_tender(_tender(title="Rail Signaling"), "hash-1")
    store.save_research("t-1", _research())

    from detection.normalize import compute_dedup_hash

    new_hash = compute_dedup_hash("Rail Signaling (Revised)", "MetroDOT")
    assert new_hash != "hash-1"
    store.save_tender(_tender(title="Rail Signaling (Revised)"), new_hash)

    updated = store.get_tender("t-1")
    assert updated is not None and updated.title == "Rail Signaling (Revised)"
    assert store.find_by_hash(new_hash) is not None
    assert store.get_research("t-1") is not None, "an edited tender lost its research"


def test_reingest_refreshes_every_mutable_column():
    """REPLACE reset omitted columns to defaults; DO UPDATE SET must be explicit."""
    store.save_tender(_tender(), "hash-1")
    changed = _tender(
        title="New Title", issuer="New Issuer", status="processed",
    )
    changed = changed.model_copy(update={
        "sector": "Custom Software Development",
        "requirements": ["Updated requirement"],
    })
    store.save_tender(changed, "hash-2")

    stored = store.get_tender("t-1")
    assert stored.title == "New Title"
    assert stored.issuer == "New Issuer"
    assert stored.sector == "Custom Software Development"
    assert stored.requirements == ["Updated requirement"]
    assert stored.status == "processed"
    assert stored.raw_text == _tender().raw_text, "untouched column was blanked"


def test_research_is_replaced_not_duplicated_for_one_tender():
    """Re-running research must overwrite, since tender_id is the primary key."""
    research = ProspectResearch(
        tender_id="t-1", issuer="MetroDOT", sector="Transit",
        estimated_revenue="$1.2B", past_projects=["Signaling"],
        key_partners=["Stellar Civil"], notes="", confidence="medium",
        sources=["https://mdot.example"],
    )
    store.save_tender(_tender(), "hash-1")
    store.save_research("t-1", research)
    research.confidence = "high"
    research.notes = "second pass"
    store.save_research("t-1", research)

    stored = store.get_research("t-1")
    assert stored.confidence == "high"
    assert stored.notes == "second pass"
    assert stored.sources == ["https://mdot.example"]


def test_is_expired_is_derived_on_read_not_frozen_at_ingest():
    """A stored deadline that has since passed must read as expired.

    `is_expired` was written once at ingest; a tender ingested with a
    future deadline and read back after that date kept reporting
    is_expired=False, so nothing downstream (research skip, triage) ever saw
    it close. Expiry is a function of "now", so it is recomputed on read.
    """
    from datetime import date, timedelta

    stale = _tender()
    stale.deadline = date.today() - timedelta(days=1)
    stale.quality.is_expired = False  # as it would have been stored while live
    store.save_tender(stale, "hash-stale")

    found = store.get_tender("t-1")
    assert found is not None
    assert found.quality.is_expired is True


def test_future_deadline_reads_as_not_expired():
    store.save_tender(_tender(), "hash-1")  # deadline 2026-12-01
    assert store.get_tender("t-1").quality.is_expired is False


def test_deleting_research_reports_whether_a_row_went_away():
    research = ProspectResearch(
        tender_id="t-1", issuer="MetroDOT", sector=None, estimated_revenue=None,
        past_projects=[], key_partners=[], notes="", confidence="low", sources=[],
    )
    store.save_tender(_tender(), "hash-1")
    store.save_research("t-1", research)
    assert store.delete_research("t-1") is True
    assert store.delete_research("t-1") is False, "second delete must report no-op"


def test_set_status_updates_only_the_status():
    store.save_tender(_tender(), "hash-1")
    updated = store.set_status("t-1", "archived")
    assert updated is not None and updated.status == "archived"
    stored = store.get_tender("t-1")
    assert stored.status == "archived"
    assert stored.title == "Rail Signaling" and stored.requirements == ["OWASP top 10 testing"]


def test_set_status_unknown_tender_returns_none():
    assert store.set_status("missing", "archived") is None


def test_set_status_keeps_research():
    store.save_tender(_tender(), "hash-1")
    store.save_research("t-1", _research())
    store.set_status("t-1", "archived")
    assert store.get_research("t-1") is not None


def test_research_facts_round_trip():
    from shared.schemas import ResearchFact

    facts = [
        ResearchFact(value="Transit", category="sector", confidence="high", source="https://a.example/x"),
        ResearchFact(value="BuildCo", category="key_partners", confidence="low", source="https://b.example/y"),
    ]
    store.save_tender(_tender(), "hash-1")
    store.save_research("t-1", _research().model_copy(update={"facts": facts}))
    assert store.get_research("t-1").facts == facts


def test_research_row_from_before_facts_reads_with_no_facts(tmp_path, monkeypatch):
    import sqlite3

    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(legacy))
    conn.executescript(
        """
        CREATE TABLE research (
            tender_id TEXT PRIMARY KEY,
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
        INSERT INTO research (tender_id, issuer, sector, past_projects, key_partners, confidence, sources)
        VALUES ('t-old', 'MetroDOT', 'Transit', '[]', '[]', 'low', '["https://a.example"]');
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(store, "DB_PATH", legacy)
    store.init_db()
    store.init_db()
    old = store.get_research("t-old")
    assert old.facts == []
    assert old.sources == ["https://a.example"]


def test_notice_details_round_trip_through_the_store():
    from datetime import date

    t = _tender().model_copy(update={
        "issuer_country": "FRA", "notice_type": "cn-standard",
        "published_at": date(2026, 10, 22), "links": ["https://a.example/x.pdf"],
    })
    store.save_tender(t, "h-notice")
    back = store.get_tender("t-1")
    assert (back.issuer_country, back.notice_type, back.published_at, back.links) == (
        "FRA", "cn-standard", date(2026, 10, 22), ["https://a.example/x.pdf"])


def test_notice_details_survive_set_status_and_a_status_preserving_resave():
    t = _tender().model_copy(update={"issuer_country": "FRA", "links": ["https://a.example"]})
    store.save_tender(t, "h-notice")
    store.set_status("t-1", "archived")
    assert store.get_tender("t-1").issuer_country == "FRA"
    assert store.get_tender("t-1").links == ["https://a.example"]


def _pre_s8_db(path, with_v2_columns):
    import sqlite3

    conn = sqlite3.connect(path)
    extra = ("quality_completeness REAL NOT NULL DEFAULT 1.0, quality_missing TEXT NOT NULL DEFAULT '[]', "
             "quality_warnings TEXT NOT NULL DEFAULT '[]', quality_is_expired INTEGER NOT NULL DEFAULT 0, "
             if with_v2_columns else "")
    deadline = "deadline TEXT" if with_v2_columns else "deadline TEXT NOT NULL"
    conn.execute(f"""CREATE TABLE tenders (id TEXT PRIMARY KEY, title TEXT NOT NULL, issuer TEXT NOT NULL,
        sector TEXT NOT NULL, requirements TEXT NOT NULL, {deadline}, raw_text TEXT NOT NULL,
        source TEXT NOT NULL, detected_at TEXT NOT NULL, status TEXT NOT NULL, {extra} dedup_hash TEXT UNIQUE)""")
    conn.execute("""INSERT INTO tenders (id, title, issuer, sector, requirements, deadline, raw_text, source,
        detected_at, status, dedup_hash) VALUES ('tender-001', 'Old tender', 'Old Issuer', 'unknown', '[]',
        '2026-12-01', 'text', 'manual', '2026-01-01T00:00:00+00:00', 'new', 'old-hash')""")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("with_v2_columns", [True, False])
def test_pre_s8_database_migrates(tmp_path, monkeypatch, with_v2_columns):
    db = tmp_path / "pre_s8.db"
    _pre_s8_db(db, with_v2_columns)
    monkeypatch.setattr(store, "DB_PATH", db)
    store.init_db()
    old = store.get_tender("tender-001")
    assert old.links == []
    assert (old.issuer_country, old.notice_type, old.published_at) == (None, None, None)
    store.init_db()
    assert store.get_tender("tender-001").links == []
