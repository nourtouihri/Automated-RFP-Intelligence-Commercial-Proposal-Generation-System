"""Strict, read-only JSONL loading for the isolated retrieval experiment."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from rag.doc_types import normalize_doc_type
from rag.evaluate_local import LocalRetriever, load_corpus


def normalize_document(row: dict[str, Any], *, location: str) -> dict[str, Any]:
    """Normalize legacy and prepared chunks to the shared RAG chunk schema."""
    if not isinstance(row, dict):
        raise ValueError(f"{location}: each chunk must be a JSON object")
    content = row.get("content", row.get("text"))
    if not isinstance(content, str):
        raise ValueError(f"{location}: content (or text) must be a string")
    metadata = row.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError(f"{location}: metadata must be an object")
    record_id = metadata.get("record_id", row.get("record_id"))
    if record_id is None and "text" in row and "id" in row:
        record_id = row["id"]
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError(f"{location}: explicit string record_id is required; chunk IDs are not record IDs")
    if (
        "record_id" in metadata and "record_id" in row
        and metadata["record_id"] != row["record_id"]
    ):
        raise ValueError(f"{location}: conflicting record_id fields")
    raw_type = row.get("doc_type", metadata.get("doc_type"))
    doc_type = normalize_doc_type(raw_type)
    if doc_type is None:
        raise ValueError(f"{location}: doc_type is required")
    source_file = row.get("source_file", Path(location.split(":", 1)[0]).name)
    if not isinstance(source_file, str) or not source_file.strip():
        raise ValueError(f"{location}: source_file must be a non-empty string")
    chunk_id = row.get("id")
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        chunk_id = f"{source_file}:{location.rsplit(':', 1)[-1]}"
    title = row.get("title", "")
    if not isinstance(title, str):
        raise ValueError(f"{location}: title must be a string")
    lang = row.get("lang", "en")
    if not isinstance(lang, str) or not lang.strip():
        raise ValueError(f"{location}: lang must be a non-empty string")
    synthetic = row.get("synthetic", False)
    if not isinstance(synthetic, bool):
        raise ValueError(f"{location}: synthetic must be a boolean")
    chunk_version = row.get("chunk_version", "v1")
    if not isinstance(chunk_version, str) or not chunk_version.strip():
        raise ValueError(f"{location}: chunk_version must be a non-empty string")
    content_hash = row.get(
        "content_hash", hashlib.sha256(content.encode("utf-8")).hexdigest()
    )
    if not isinstance(content_hash, str) or not content_hash.strip():
        raise ValueError(f"{location}: content_hash must be a non-empty string")
    return {
        **row,
        "id": chunk_id,
        "content": content,
        "text": content,
        "doc_type": doc_type,
        "title": title,
        "lang": lang,
        "synthetic": synthetic,
        "source_file": source_file,
        "chunk_version": chunk_version,
        "content_hash": content_hash,
        "source_doc_type": raw_type,
        "metadata": {**metadata, "record_id": record_id},
    }


def load_jsonl_corpus(path: Path) -> list[dict]:
    """Load all chunks, keeping blank content and exact record IDs intact."""
    if not path.is_file():
        raise ValueError(f"Canonical corpus not found: {path}. Supply --chunks or explicitly use --bundled.")
    documents = []
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            location = f"{path}:{line_number}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{location}: invalid JSON: {exc.msg}") from exc
            documents.append(normalize_document(row, location=location))
    if not documents:
        raise ValueError(f"{path}: corpus contains no chunks")
    return documents


def load_bundled_corpus() -> list[dict]:
    """Use the original source-record loader, only when explicitly requested."""
    data = Path("Cvs dataset")
    return load_corpus(
        data / "fake_cvs.json", data / "fake_projects.json",
        data / "fake_tools.json", data / "olivesoft_projects.json",
    )


class CanonicalSemanticRetriever:
    """Normalize the query filter and delegate all scoring to the baseline."""

    def __init__(self, retriever: LocalRetriever):
        self.retriever = retriever

    def __call__(self, text: str, *, top_k: int, doc_type: str | None = None) -> list[dict]:
        return self.retriever(text, top_k=top_k, doc_type=normalize_doc_type(doc_type))
