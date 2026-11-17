import json

from .upstream import Upstream

TOP_K = 5
SIMILARITY_THRESHOLD = 0.20


def _requirement_text(requirement) -> str:
    if isinstance(requirement, str):
        return requirement
    if isinstance(requirement, dict) and requirement.get("text"):
        return requirement["text"]
    return json.dumps(requirement, separators=(",", ":"), ensure_ascii=False)


def rag_query(tender: dict) -> str:
    """The text n8n's "Prepare RAG Context" builds. It also reads description and
    categories, which the detection service does not store, so they are left out."""
    requirements = tender.get("requirements")
    if not isinstance(requirements, list):
        requirements = []
    parts = [
        tender.get("title") or "",
        tender.get("issuer") or "",
        *(_requirement_text(r) for r in requirements),
    ]
    return "\n".join(part for part in parts if part)


def _keep_hits(body) -> list[dict]:
    values = body if isinstance(body, list) else [body]
    return [v for v in values if isinstance(v, dict) and v.get("id")]


def team_matches(
    upstream: Upstream, tender: dict, request_id: str | None
) -> tuple[list[dict], list[dict]]:
    text = rag_query(tender)
    matches = []
    for doc_type in ("cv", "project"):
        _, body = upstream.call(
            "rag",
            "POST",
            "/query",
            json={
                "text": text,
                "top_k": TOP_K,
                "doc_type": doc_type,
                "similarity_threshold": SIMILARITY_THRESHOLD,
            },
            request_id=request_id,
        )
        matches.append(_keep_hits(body))
    return matches[0], matches[1]


def hits_by_record(*match_lists: list[dict]) -> dict[str, dict]:
    hits = {}
    for matches in match_lists:
        for hit in matches:
            record_id = (hit.get("metadata") or {}).get("record_id")
            if record_id:
                hits.setdefault(str(record_id), hit)
    return hits
