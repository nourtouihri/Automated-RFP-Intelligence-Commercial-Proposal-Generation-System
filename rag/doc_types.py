"""Shared offline-experiment type aliases; record IDs are never normalized.

The checked-in baseline has no alias table. These explicit compatibility
aliases support the requested JSONL format without changing production schemas.
Client records retain their distinct type rather than being merged into projects.
"""

DOC_TYPE_ALIASES = {
    "cv": "cv",
    "project": "project",
    "olivesoft_project": "project",
    "project_reference": "project",
    "tool": "tool",
    "capability": "tool",
    "technology": "tool",
    "stack_by_domain": "tool",
    "client": "client",
}


def normalize_doc_type(doc_type: str | None) -> str | None:
    """Canonicalize known aliases and preserve other nonempty type names."""
    if doc_type is None:
        return None
    if not isinstance(doc_type, str) or not doc_type.strip():
        raise ValueError("doc_type must be a non-empty string or None")
    normalized = doc_type.strip().lower()
    return DOC_TYPE_ALIASES.get(normalized, normalized)
