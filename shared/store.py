"""
SQLite persistence for tenders and prospect research: WAL mode with a UNIQUE
dedup_hash column to keep duplicate ingests idempotent at the storage layer.

Schema versioning: ``PRAGMA user_version`` gates rebuild migrations that
SQLite cannot express as ALTER TABLE (dropping NOT NULL, changing a hash
scheme). v2 rebuilds ``tenders`` to make ``deadline`` nullable, add the
``quality_*`` columns, and recompute every stored ``dedup_hash`` with the v2
canonicalization (accent-folded, punctuation-stripped, legal-suffix-free).
Without the recompute, every pre-v2 row would re-ingest as a fresh duplicate.

Connection discipline: every helper opens its own connection and closes it in
a ``finally`` block (via the ``_connect()`` context manager). The previous
version called ``conn.close()`` only on the happy path, so a failed INSERT
leaked the connection while the traceback kept the frame alive, holding a
write lock that broke every subsequent test with "database is locked".
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional

from shared.dedup import canonical_key
from shared.errors import ApiError, ErrorCode
from shared.schemas import DataQuality, ProspectResearch, Tender
from proposal.schemas import Proposal, NoBid

logger = logging.getLogger(__name__)


@dataclass
class _DeckResult:
    """Supports both attribute access and tuple-like destructuring:
    
    result = store.get_deck_by_tender_id_and_metadata(tender_id)
    deck, artifacts, checks, trace = result
    
    Or: deck = result.deck
    """
    deck: Proposal | NoBid
    artifacts: dict[str, str | None]
    checks: dict[str, bool]
    trace: list[dict]

    def __iter__(self):
        yield self.deck
        yield self.artifacts
        yield self.checks
        yield self.trace

SCHEMA_VERSION = 2

DB_PATH = Path(
    os.environ.get("OLIVESOFT_DB_PATH", str(Path(__file__).parent / "sqlite.db"))
)


def _row_to_tender(row: sqlite3.Row) -> Tender:
    d = dict(row)
    d["requirements"] = json.loads(d["requirements"])
    if isinstance(d.get("deadline"), str):
        d["deadline"] = date.fromisoformat(d["deadline"])
    if isinstance(d.get("detected_at"), str):
        d["detected_at"] = datetime.fromisoformat(d["detected_at"])
    deadline = d.get("deadline")
    d.pop("quality_is_expired", None)
    d["quality"] = DataQuality(
        completeness=float(d.pop("quality_completeness", 1.0) or 0.0),
        missing_fields=json.loads(d.pop("quality_missing", None) or "[]"),
        warnings=json.loads(d.pop("quality_warnings", None) or "[]"),
        # Expiry is a function of "now", not a fact frozen at ingest time: a
        # stored deadline that has since passed must read as expired without
        # waiting for a re-ingest that a stale tender may never receive.
        is_expired=deadline is not None and deadline < date.today(),
    )
    if isinstance(d.get("published_at"), str):
        d["published_at"] = date.fromisoformat(d["published_at"])
    d["links"] = json.loads(d.get("links") or "[]")
    d.pop("dedup_hash", None)
    return Tender(**d)

def _row_to_research(row: sqlite3.Row) -> ProspectResearch:
    d = dict(row)
    d["past_projects"] = json.loads(d["past_projects"])
    d["key_partners"] = json.loads(d["key_partners"])
    d["sources"] = json.loads(d["sources"])
    d["facts"] = json.loads(d.get("facts") or "[]")
    if isinstance(d.get("completed_at"), str):
        try:
            d["completed_at"] = datetime.fromisoformat(d["completed_at"].replace("Z", "+00:00"))
        except Exception:
            d["completed_at"] = None
    return ProspectResearch(**d)

def _row_to_deck(row: sqlite3.Row) -> Proposal | NoBid:
    d = dict(row)
    kind = d.pop("kind")
    deck = json.loads(d.pop("deck") or "{}")
    created_at = d.pop("created_at", None)
    # The row columns are authoritative over whatever the deck JSON carries:
    # save_deck stamps updated_at on every write, which is the version a
    # review's optimistic-concurrency token is checked against.
    updated_at = d.pop("updated_at", None)
    # Extract checks and trace from the row
    d.pop("checks", None)
    d.pop("trace", None)
    if kind == "no_bid":
        return NoBid.model_validate({**deck, "created_at": created_at,
                                     "updated_at": updated_at,
                                     "review_status": d.pop("review_status") or "draft",
                                     "recommendation": deck.get("recommendation") or ""})

    deck["created_at"] = created_at
    deck["updated_at"] = updated_at
    deck["review_status"] = d.pop("review_status") or "draft"
    return Proposal.model_validate(deck)


def _row_to_proposal(row: sqlite3.Row) -> Proposal | None:
    d = dict(row)
    deck = json.loads(d.pop("deck") or "{}")
    created_at = d.pop("created_at", None)

    deck["created_at"] = created_at
    deck["updated_at"] = d.pop("updated_at", None)
    deck["review_status"] = d.pop("review_status") or "draft"
    return Proposal.model_validate(deck)


def _parse_checks(value) -> dict[str, bool]:
    """Parse checks JSON from DB, returning empty dict on failure."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_trace(value) -> list[dict]:
    """Parse trace JSON from DB, returning empty list on failure."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _parse_artifacts(value) -> dict[str, str | None]:
    """Parse artifacts JSON from DB, returning empty dict on failure."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Yield a configured connection, always closing it — even on error."""
    conn = _get_conn()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _create_tenders_sql(table: str) -> str:
    """DDL for the v2 tenders shape (nullable deadline, quality columns)."""
    return f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                issuer TEXT NOT NULL,
                sector TEXT NOT NULL,
                requirements TEXT NOT NULL,
                deadline TEXT,
                raw_text TEXT NOT NULL,
                source TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                status TEXT NOT NULL,
                quality_completeness REAL NOT NULL DEFAULT 1.0,
                quality_missing TEXT NOT NULL DEFAULT '[]',
                quality_warnings TEXT NOT NULL DEFAULT '[]',
                quality_is_expired INTEGER NOT NULL DEFAULT 0,
                dedup_hash TEXT UNIQUE,
                issuer_country TEXT,
                notice_type TEXT,
                published_at TEXT,
                links TEXT NOT NULL DEFAULT '[]'
            )
        """


def _rebuild_tenders_v2(conn: sqlite3.Connection) -> None:
    """Rebuild tenders with the v2 shape and recompute every dedup hash.

    Runs with foreign keys OFF (see init_db): research.tender_id references
    tenders(id) by name, so DROP + RENAME is safe as long as the rebuild does
    not trigger cascades. A v2-canonicalization collision between two stored
    rows keeps the earliest row's hash and clears the later row's (UNIQUE
    permits multiple NULLs) — near-duplicates are flagged, never auto-merged.
    """
    rows = conn.execute("SELECT * FROM tenders").fetchall()
    conn.execute("DROP TABLE IF EXISTS tenders_v2")
    conn.execute(_create_tenders_sql("tenders_v2"))

    seen_hashes: set[str] = set()
    collisions = 0
    for row in rows:
        d = dict(row)
        new_hash = canonical_key(d["title"], d["issuer"])
        if new_hash in seen_hashes:
            new_hash = None
            collisions += 1
        else:
            seen_hashes.add(new_hash)
        conn.execute(
            """INSERT INTO tenders_v2
               (id, title, issuer, sector, requirements, deadline, raw_text,
                source, detected_at, status, quality_completeness,
                quality_missing, quality_warnings, quality_is_expired, dedup_hash,
                issuer_country, notice_type, published_at, links)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, '[]', '[]', 0, ?, ?, ?, ?, ?)""",
            (
                d["id"], d["title"], d["issuer"], d["sector"], d["requirements"],
                d["deadline"], d["raw_text"], d["source"], d["detected_at"],
                d["status"], new_hash,
                d.get("issuer_country"), d.get("notice_type"), d.get("published_at"),
                d.get("links") or "[]",
            ),
        )

    conn.execute("DROP TABLE tenders")
    conn.execute("ALTER TABLE tenders_v2 RENAME TO tenders")
    if collisions:
        logger.warning(
            "tenders v2 migration: %d dedup-hash collision(s) cleared "
            "(earliest row keeps the key; review manually)", collisions
        )
    logger.info("tenders v2 migration: rebuilt %d row(s) with v2 dedup hashes", len(rows))


def init_db() -> None:
    with _connect() as conn:
        # The v2 rebuild DROPs and recreates the table research.tender_id
        # references; with foreign keys ON that would cascade-delete every
        # research row. The standard SQLite recipe is to run the rebuild with
        # enforcement disabled, then turn it back on.
        conn.execute("PRAGMA foreign_keys=OFF")

        conn.execute(_create_tenders_sql("tenders"))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research (
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
                completed_at TEXT,
                facts TEXT NOT NULL DEFAULT '[]'
            )
        """)
        conn.execute(
            """
                CREATE TABLE IF NOT EXISTS proposals (
                    tender_id      TEXT PRIMARY KEY,
                    kind           TEXT NOT NULL,   -- "proposal" | "no_bid"
                    review_status  TEXT NOT NULL DEFAULT 'draft',
                    deck           TEXT NOT NULL,   -- JSON text of the Proposal / NoBid payload
                    warnings       TEXT NOT NULL DEFAULT '[]',  -- JSON list[str]
                    artifacts      TEXT NOT NULL DEFAULT '{}',  -- JSON dict[str, str | None]
                    checks         TEXT NOT NULL DEFAULT '{}',  -- JSON dict[str, bool]
                    trace          TEXT NOT NULL DEFAULT '[]',  -- JSON list[dict]
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT 
                )
            """
        )
        
        # Migration for DBs created before issuer/notes/status/completed_at columns existed.
        for col, ddl in (
            ("issuer", "ALTER TABLE research ADD COLUMN issuer TEXT NOT NULL DEFAULT ''"),
            ("notes", "ALTER TABLE research ADD COLUMN notes TEXT NOT NULL DEFAULT ''"),
            ("status", "ALTER TABLE research ADD COLUMN status TEXT"),
            ("completed_at", "ALTER TABLE research ADD COLUMN completed_at TEXT"),
            ("facts", "ALTER TABLE research ADD COLUMN facts TEXT NOT NULL DEFAULT '[]'"),
        ):
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(research)").fetchall()}
            if col not in cols:
                conn.execute(ddl)

        # Add checks and trace columns to proposals table if missing
        for col, ddl in (
            ("checks", "ALTER TABLE proposals ADD COLUMN checks TEXT NOT NULL DEFAULT '{}'"),
            ("trace", "ALTER TABLE proposals ADD COLUMN trace TEXT NOT NULL DEFAULT '[]'"),
        ):
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(proposals)").fetchall()}
            if col not in cols:
                conn.execute(ddl)

        # Rebuild detection is by actual table shape (not user_version alone),
        # so hand-built legacy DBs and partially migrated files both heal.
        info = {r["name"]: r for r in conn.execute("PRAGMA table_info(tenders)").fetchall()}
        deadline_column = info.get("deadline")
        needs_rebuild = "quality_completeness" not in info or bool(
            deadline_column["notnull"] if deadline_column is not None else 0
        )
        if needs_rebuild:
            _rebuild_tenders_v2(conn)

        # S8 notice details; the v2 rebuild already creates them, so this heals pre-S8 files.
        for col, ddl in (
            ("issuer_country", "ALTER TABLE tenders ADD COLUMN issuer_country TEXT"),
            ("notice_type", "ALTER TABLE tenders ADD COLUMN notice_type TEXT"),
            ("published_at", "ALTER TABLE tenders ADD COLUMN published_at TEXT"),
            ("links", "ALTER TABLE tenders ADD COLUMN links TEXT NOT NULL DEFAULT '[]'"),
        ):
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(tenders)").fetchall()}
            if col not in cols:
                conn.execute(ddl)

        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            logger.error(
                "foreign_key_check reported %d issue(s) after migration: %s",
                len(broken), [tuple(r) for r in broken[:5]],
            )

        # SQLite rejects bound parameters in PRAGMA statements ("near \"?\":
        # syntax error"), so the version must be interpolated. SCHEMA_VERSION
        # is a trusted module-level int constant, never request data, so this
        # cannot be injected; semgrep's formatted-sql-query rule is a false
        # positive here.
        conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")

## ========== Tenders CRUD ==========
def save_tender(tender: Tender, dedup_hash: str) -> None:
    """Insert a tender, or update it in place, without ever deleting the row.

    This was ``INSERT OR REPLACE``, which is a DELETE followed by an INSERT.
    Combined with ``research.tender_id ... ON DELETE CASCADE`` that silently
    destroyed the computed research for a tender on *every* re-ingest — not
    just the concurrent-duplicate case: a plain ``status: new -> processed``
    transition, or a sheet edit that changed the title, both wiped it. The
    tender row looked fine, so the loss was invisible.

    Two distinct conflicts need two distinct answers, hence two clauses:

    - ``ON CONFLICT(dedup_hash)`` — a duplicate ingest that arrived with a
      different id (each ingest mints a random uuid). Update the content but
      keep the *existing* id, so research already keyed to that id stays
      attached instead of being orphaned.
    - ``ON CONFLICT(id)`` — the same id re-sent with edited content, so the
      hash moved too. Keep the id, refresh everything including the hash.
      Without this clause a PRIMARY KEY conflict would raise IntegrityError,
      because the hash clause alone does not cover the id index.

    ``id`` is deliberately never reassigned in either clause: the id is the
    research foreign key, and changing it would break the link in both
    directions. Every other mutable column is listed explicitly rather than
    relying on REPLACE's reset-to-default behaviour, which would blank any
    column omitted from the SET list.
    """
    content_columns = """
           title = excluded.title, issuer = excluded.issuer, sector = excluded.sector,
           requirements = excluded.requirements, deadline = excluded.deadline,
           raw_text = excluded.raw_text, source = excluded.source,
           detected_at = excluded.detected_at, status = excluded.status,
           quality_completeness = excluded.quality_completeness,
           quality_missing = excluded.quality_missing,
           quality_warnings = excluded.quality_warnings,
           quality_is_expired = excluded.quality_is_expired,
           issuer_country = excluded.issuer_country, notice_type = excluded.notice_type,
           published_at = excluded.published_at, links = excluded.links"""
    with _connect() as conn:
        try:
            conn.execute(
                f"""INSERT INTO tenders
                   (id, title, issuer, sector, requirements, deadline, raw_text,
                    source, detected_at, status, quality_completeness,
                    quality_missing, quality_warnings, quality_is_expired,
                    dedup_hash, issuer_country, notice_type, published_at, links)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(dedup_hash) DO UPDATE SET{content_columns}
                   ON CONFLICT(id) DO UPDATE SET{content_columns},
                       dedup_hash = excluded.dedup_hash""",
                (
                    tender.id, tender.title, tender.issuer, tender.sector,
                    json.dumps(tender.requirements),
                    tender.deadline.isoformat() if tender.deadline else None,
                    tender.raw_text, tender.source, tender.detected_at.isoformat(),
                    tender.status,
                    tender.quality.completeness,
                    json.dumps(tender.quality.missing_fields),
                    json.dumps(tender.quality.warnings),
                    1 if tender.quality.is_expired else 0,
                    dedup_hash,
                    tender.issuer_country, tender.notice_type,
                    tender.published_at.isoformat() if tender.published_at else None,
                    json.dumps(tender.links),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_tender(tender_id: str) -> Optional[Tender]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()
        return _row_to_tender(row) if row else None


def set_status(
    tender_id: str, status: Literal["new", "incomplete", "processed", "archived"]
) -> Optional[Tender]:
    """Change only the status column; the row is updated in place, never replaced."""
    with _connect() as conn:
        cursor = conn.execute("UPDATE tenders SET status = ? WHERE id = ?", (status, tender_id))
        conn.commit()
        if cursor.rowcount == 0:
            return None
    return get_tender(tender_id)


def find_by_hash(dedup_hash: str) -> Optional[Tender]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tenders WHERE dedup_hash = ?", (dedup_hash,)).fetchone()
        return _row_to_tender(row) if row else None


def list_tenders(status: Optional[str] = None) -> list[Tender]:
    with _connect() as conn:
        if status:
            rows = conn.execute("SELECT * FROM tenders WHERE status = ?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tenders").fetchall()
        return [_row_to_tender(r) for r in rows]


## ========== Research CRUD ==========
def save_research(tender_id: str, research: ProspectResearch) -> None:
    with _connect() as conn:
        try:
            completed_at = None
            if research.completed_at is not None:
                try:
                    completed_at = research.completed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                except Exception:
                    completed_at = research.completed_at.isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO research
                   (tender_id, issuer, sector, estimated_revenue, past_projects,
                    key_partners, notes, confidence, sources, status, completed_at, facts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tender_id,
                    research.issuer,
                    research.sector,
                    research.estimated_revenue,
                    json.dumps(research.past_projects),
                    json.dumps(research.key_partners),
                    research.notes,
                    research.confidence,
                    json.dumps(research.sources),
                    research.status,
                    completed_at,
                    json.dumps([f.model_dump() for f in research.facts]),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_research(tender_id: str) -> Optional[ProspectResearch]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM research WHERE tender_id = ?", (tender_id,)).fetchone()
        return _row_to_research(row) if row else None


def get_research_by_issuer(issuer: str) -> Optional[ProspectResearch]:
    """Issuer-keyed cache lookup: latest stored research for any tender of this issuer.

    Lets a repeated run for the same organization (or a second tender from the
    same issuer) be served without re-spending search/LLM budget.
    """
    with _connect() as conn:
        # rowid is the insertion counter, so this is true recency. ORDER BY
        # tender_id would be lexicographic on an opaque id ("t10" < "t2").
        row = conn.execute(
            "SELECT * FROM research WHERE issuer = ? ORDER BY rowid DESC LIMIT 1",
            (issuer,),
        ).fetchone()
        return _row_to_research(row) if row else None

def get_research_by_tender_id(tender_id:str)-> Optional[ProspectResearch]:
    """tender_id-keyed cache lookup: latest stored research for specific tender

    Lets a repeated run for the same organization (or a second tender from the
    same issuer) be served without re-spending search/LLM budget.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM research WHERE tender_id = ? ",
            (tender_id,),
        ).fetchone()
        return _row_to_research(row) if row else None

def list_research() -> dict[str, ProspectResearch]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM research").fetchall()
        return {r["tender_id"]: _row_to_research(r) for r in rows}


def delete_research(tender_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM research WHERE tender_id = ?", (tender_id,))
        conn.commit()
        return cur.rowcount > 0

## ========== Proposals CRUD ==========
def save_deck(tender_id: str, deck: Proposal | NoBid,
                  warnings: list[str] | None = None,
                  artifacts: dict[str, str | None] | None = None,
                  checks: dict[str, bool] | None = None,
                  trace: list[dict] | None = None,
                  review_status: str | None = None) -> None:
    """Insert the deck or update the stored row for the same tender.

    An insert sets created_at = updated_at = now and defaults review_status
    to "draft". An update keeps created_at, replaces the deck with the one
    passed in, and keeps review_status/warnings/artifacts/checks/trace the
    caller did not supply (COALESCE): a prompt-edit re-saves the deck without
    wiping the artifacts index or a reviewer's decision. The mutable defaults
    are None on purpose — an empty list would erase the stored
    warnings/artifacts on every update; passing [] re-empties them explicitly.
    """
    deck.review_status = review_status
    deck_json = deck.model_dump_json()
    kind = "proposal" if isinstance(deck, Proposal) else "no_bid"
    now = datetime.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    warnings_json = json.dumps(warnings) if warnings is not None else None
    artifacts_json = json.dumps(artifacts) if artifacts is not None else None
    checks_json = json.dumps(checks) if checks is not None else None
    trace_json = json.dumps(trace) if trace is not None else None
    with _connect() as conn:
        try:
            cur = conn.execute(
                """UPDATE proposals SET
                       kind = ?,
                       deck = ?,
                       review_status = COALESCE(?, review_status),
                       warnings = COALESCE(?, warnings),
                       artifacts = COALESCE(?, artifacts),
                       checks = COALESCE(?, checks),
                       trace = COALESCE(?, trace),
                       updated_at = ?
                   WHERE tender_id = ?""",
                (kind, deck_json, review_status, warnings_json, artifacts_json,
                 checks_json, trace_json, now, tender_id))
            if cur.rowcount == 0:
                conn.execute(
                    """INSERT INTO proposals
                       (tender_id, kind, review_status, deck, warnings, artifacts,
                        checks, trace, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tender_id, kind, review_status or "draft", deck_json,
                     warnings_json if warnings_json is not None else "[]",
                     artifacts_json if artifacts_json is not None else "{}",
                     checks_json if checks_json is not None else "{}",
                     trace_json if trace_json is not None else "[]",
                     now, now))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_deck_by_tender_id(tender_id: str) -> Proposal | NoBid | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE tender_id = ?", (tender_id,)).fetchone()
    return _row_to_deck(row) if row is not None else None

def get_proposal_by_tender_id(tender_id:str, review_status:Literal["draft", "accepted", "refused"]="draft") -> Proposal | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE tender_id = ? and kind='proposal' and review_status=?", (tender_id,review_status)).fetchone()
        return _row_to_proposal(row) if row is not None else None


def get_deck_by_tender_id_and_review_status(tender_id:str, review_status:Literal["draft", "accepted", "refused"]="draft") -> Proposal | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE tender_id = ? and review_status=?", (tender_id,review_status)).fetchone()
        return _row_to_deck(row) if row is not None else None


def get_deck_by_tender_id_and_metadata(tender_id: str) -> _DeckResult:
    """Fetch a deck with its artifacts, checks, and trace from the DB.

    Returns _DeckResult(deck, artifacts, checks, trace) supporting both
    attribute access and tuple destructuring:

        deck, artifacts, checks, trace = store.get_deck_by_tender_id_and_metadata(tid)

    or when only the deck is needed:

        deck, _, _, _ = store.get_deck_by_tender_id_and_metadata(tid)

    Raises ApiError(404) when no deck row exists for the tender id.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM proposals WHERE tender_id = ?",
            (tender_id,),
        ).fetchone()
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No deck found for tender " + tender_id, status_code=404)
    deck = _row_to_deck(row)
    artifacts = _parse_artifacts(row["artifacts"])
    checks = _parse_checks(row["checks"])
    trace = _parse_trace(row["trace"])
    return _DeckResult(deck=deck, artifacts=artifacts, checks=checks, trace=trace)


def get_deck_artifacts(tender_id: str) -> dict[str, str | None] | None:
    """The row's artifact index (file name -> served name), or None when no
    deck row exists. This is the allowlist /proposal/{id}/files serves from;
    the deck JSON itself never carries artifacts."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT artifacts FROM proposals WHERE tender_id = ?", (tender_id,)
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["artifacts"] or "{}")
    except (TypeError, ValueError):
        return {}

def list_decks() -> list[Proposal | NoBid]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM proposals ORDER BY rowid DESC").fetchall()
    return [_row_to_deck(r) for r in rows]


def _parse_warnings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def list_decks_entries() -> list[dict]:
    """Row identity plus the hydrated deck, newest first, for the review screen.

    list_proposals() answers "what decks exist"; this one also answers "which
    tender, what kind, what review state" — everything a list endpoint shows
    before anyone opens one deck. The deck itself is id-less (Proposal carries
    no tender_id), so the row key travels beside it instead of inside it.
    """
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM proposals ORDER BY rowid DESC").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        out.append({
            "tender_id": d["tender_id"],
            "kind": d["kind"],
            "review_status": d["review_status"] or "draft",
            "warnings": _parse_warnings(d["warnings"]),
            "deck": _row_to_deck(row),
        })
    return out