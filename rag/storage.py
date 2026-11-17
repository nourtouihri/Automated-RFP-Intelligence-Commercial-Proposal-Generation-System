"""Failure-safe persistence helpers for RAG knowledge chunks."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
import uuid

from rag.embeddings import EMBEDDING_DIMENSIONS

UPSERT_BATCH_SIZE = 50
COUNT_PAGE_SIZE = 1000
_ID_NAMESPACE = uuid.UUID("51f81ae7-cd4b-47b2-a407-24083ad42db5")
DOC_TYPES = ("cv", "project", "tool")


class StatsError(RuntimeError):
    """Raised when record counts cannot be read or come back malformed."""


def make_source_id(path: Path, doc_type: str, explicit: str | None = None) -> str:
    """Build a stable logical source key that avoids basename-only collisions."""
    if explicit is not None:
        cleaned = explicit.strip()
        if not cleaned:
            raise ValueError("explicit source_id must not be blank")
        return f"{doc_type}:{cleaned}"
    return f"{doc_type}:{path.parent.name}/{path.name}"


def make_chunk_id(source_id: str, chunk_index: int) -> str:
    """Return the same UUID for the same logical source/chunk position."""
    return str(uuid.uuid5(_ID_NAMESPACE, f"{source_id}:{chunk_index}"))


def build_rows(
    chunks: list[dict],
    embeddings: list[list[float]],
    *,
    doc_type: str,
    source_id: str,
    source_file: str,
) -> list[dict]:
    if doc_type not in ("cv", "project", "tool"):
        raise ValueError("doc_type must be one of: cv, project, tool")
    if len(chunks) != len(embeddings):
        raise ValueError("chunk and embedding counts do not match")

    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        if not isinstance(chunk, dict):
            raise ValueError(f"chunk {index} must be an object")
        content = chunk.get("content") if isinstance(chunk, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"chunk {index} has no content")
        title = chunk.get("title", "")
        lang = chunk.get("lang", "en")
        synthetic = chunk.get("synthetic", False)
        chunk_version = chunk.get("chunk_version", "v1")
        content_hash = chunk.get(
            "content_hash",
            hashlib.sha256(content.strip().encode("utf-8")).hexdigest(),
        )
        metadata = chunk.get("metadata", {})
        if not isinstance(title, str):
            raise ValueError(f"chunk {index} title must be a string")
        if not isinstance(lang, str) or not lang.strip():
            raise ValueError(f"chunk {index} lang must be a non-empty string")
        if not isinstance(synthetic, bool):
            raise ValueError(f"chunk {index} synthetic must be a boolean")
        if not isinstance(chunk_version, str) or not chunk_version.strip():
            raise ValueError(f"chunk {index} chunk_version must be a non-empty string")
        if not isinstance(content_hash, str) or not content_hash.strip():
            raise ValueError(f"chunk {index} content_hash must be a non-empty string")
        if not isinstance(metadata, dict):
            raise ValueError(f"chunk {index} metadata must be an object")
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"chunk {index} has {len(embedding)} dimensions; expected {EMBEDDING_DIMENSIONS}"
            )
        rows.append(
            {
                "id": make_chunk_id(source_id, index),
                "content": content.strip(),
                "text": content.strip(),
                "title": title.strip(),
                "lang": lang.strip(),
                "synthetic": synthetic,
                "doc_type": doc_type,
                "source_id": source_id,
                "source_file": source_file,
                "chunk_index": index,
                "chunk_version": chunk_version.strip(),
                "content_hash": content_hash.strip(),
                "metadata": metadata,
                "embedding": embedding,
                "updated_at": now,
            }
        )
    return rows


def replace_source_chunks(
    rows: list[dict],
    *,
    source_id: str,
    client: Any,
    batch_size: int = UPSERT_BATCH_SIZE,
) -> None:
    """Upsert new rows first and delete stale rows only after every upsert succeeds.

    A failed embed or upsert leaves the previous complete source version available.
    A partially successful upsert may temporarily add new rows, but it never deletes
    good old rows; rerunning converges to the intended deterministic set.
    """
    if not rows:
        raise ValueError("refusing to replace a source with zero chunks")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if any(row.get("source_id") != source_id for row in rows):
        raise ValueError("all rows must belong to source_id")

    response = (
        client.table("knowledge_chunks")
        .select("id")
        .eq("source_id", source_id)
        .execute()
    )
    existing_data = getattr(response, "data", None) or []
    existing_ids = {
        str(item["id"])
        for item in existing_data
        if isinstance(item, dict) and item.get("id")
    }

    for offset in range(0, len(rows), batch_size):
        client.table("knowledge_chunks").upsert(
            rows[offset : offset + batch_size], on_conflict="id"
        ).execute()

    current_ids = {str(row["id"]) for row in rows}
    stale_ids = sorted(existing_ids - current_ids)
    if stale_ids:
        client.table("knowledge_chunks").delete().in_("id", stale_ids).execute()


def _record_key(row: Any) -> tuple[str, str]:
    record_id = row.get("record_id")
    if record_id:
        return ("record", str(record_id))
    return ("source", str(row.get("source_id")))


def count_records(client: Any) -> dict[str, int]:
    """Count distinct records per doc_type, keyed by metadata record_id.

    Rows without a record_id (unstructured documents) count once per source_id.
    """
    counts: dict[str, int] = {}
    for doc_type in DOC_TYPES:
        keys: set[tuple[str, str]] = set()
        start = 0
        while True:
            try:
                response = (
                    client.table("knowledge_chunks")
                    .select("metadata->>record_id,source_id")
                    .eq("doc_type", doc_type)
                    .order("id")
                    .range(start, start + COUNT_PAGE_SIZE - 1)
                    .execute()
                )
            except Exception as exc:
                raise StatsError("record count failed") from exc
            page = getattr(response, "data", None)
            if not isinstance(page, list) or not all(isinstance(r, dict) for r in page):
                raise StatsError("record count returned an invalid response")
            keys.update(_record_key(row) for row in page)
            if len(page) < COUNT_PAGE_SIZE:
                break
            start += COUNT_PAGE_SIZE
        counts[doc_type] = len(keys)
    return counts
