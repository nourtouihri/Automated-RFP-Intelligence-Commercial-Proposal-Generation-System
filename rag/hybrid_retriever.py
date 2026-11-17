"""Rank-only semantic/BM25 fusion for the isolated retrieval experiment.

The semantic baseline already applies its existing OliveSoft metadata ranking
boost. Variant C adds no further metadata weighting (``metadata_weight=0``).
Variant D applies an explicitly bounded *multiplicative* boost after fusion,
so raw BM25 scores and cosine similarities are never added or equated.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rag.bm25_retriever import _finite_number, _positive_integer, record_id
from rag.doc_types import normalize_doc_type
from rag.ranking import MAX_PRIORITY_BOOST, ranking_score


class HybridRetriever:
    """Reciprocal rank fusion with transparent raw scores and one-based ranks.

    Both branches retrieve ``candidate_depth`` records (20 by default). Results
    are deduplicated using the exact ``metadata.record_id``. The semantic chunk
    and its original similarity/ranking score are retained when both branches
    retrieve a record. Each branch also exposes its own winning chunk in
    ``semantic_chunk`` / ``bm25_chunk``, since the two chunks may differ.
    Missing branch ranks and BM25 scores are reported as ``None``; no missing
    semantic similarity is fabricated.

    ``rrf_score = sum(1 / (rrf_c + rank))`` over the contributing branches.
    ``fused_score = rrf_score * (1 + metadata_weight * metadata_delta)``.

    Metadata delta comes from ``ranking_score(0, doc_type, metadata)`` and is
    clamped to [0, 0.10]. With weight 0.5 the extra post-fusion boost is at most
    5%, preserving the scale of RRF scores.
    """

    def __init__(
        self,
        semantic_retriever: Callable[..., list[dict[str, Any]]],
        bm25_retriever: Callable[..., list[dict[str, Any]]],
        *,
        rrf_c: float = 60.0,
        candidate_depth: int = 20,
        metadata_weight: float = 0.0,
    ) -> None:
        if not callable(semantic_retriever) or not callable(bm25_retriever):
            raise TypeError("semantic_retriever and bm25_retriever must be callable")
        rrf_c = _finite_number(rrf_c, "rrf_c")
        if rrf_c < 0:
            raise ValueError("rrf_c must be non-negative")
        _positive_integer(candidate_depth, "candidate_depth")
        metadata_weight = _finite_number(metadata_weight, "metadata_weight")
        if not 0 <= metadata_weight <= 1:
            raise ValueError("metadata_weight must be between 0 and 1")
        self.semantic_retriever = semantic_retriever
        self.bm25_retriever = bm25_retriever
        self.rrf_c = rrf_c
        self.candidate_depth = candidate_depth
        self.metadata_weight = metadata_weight

    def _ranked_unique(
        self, results: list[dict[str, Any]], doc_type: str | None
    ) -> dict[str, tuple[int, dict[str, Any]]]:
        ranked: dict[str, tuple[int, dict[str, Any]]] = {}
        for result in results:
            if not isinstance(result, dict):
                raise ValueError("retriever results must be document objects")
            identifier = record_id(result)
            result_type = normalize_doc_type(result.get("doc_type"))
            if result_type is None:
                raise ValueError("retriever results must have a document type")
            if doc_type is not None and result_type != doc_type:
                continue
            if identifier in ranked:
                continue
            if len(ranked) >= self.candidate_depth:
                break
            ranked[identifier] = (
                len(ranked) + 1,
                {**result, "doc_type": result_type, "metadata": dict(result["metadata"])},
            )
        return ranked

    def __call__(
        self, text: str, *, top_k: int, doc_type: str | None = None
    ) -> list[dict[str, Any]]:
        _positive_integer(top_k, "top_k")
        doc_type = normalize_doc_type(doc_type)
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        # The lexical tokenizer is intentionally ASCII, but the semantic model
        # may receive Arabic or other Unicode text. Only empty/punctuation-only
        # queries should suppress both branches.
        if not any(character.isalnum() for character in text):
            return []

        semantic = self._ranked_unique(
            self.semantic_retriever(text, top_k=self.candidate_depth, doc_type=doc_type),
            doc_type,
        )
        lexical = self._ranked_unique(
            self.bm25_retriever(text, top_k=self.candidate_depth, doc_type=doc_type),
            doc_type,
        )

        # Insertion order gives deterministic ties: semantic rank first, then
        # BM25 rank for records not retrieved by the semantic branch.
        identifiers = list(dict.fromkeys([*semantic, *lexical]))
        fused: list[dict[str, Any]] = []
        for identifier in identifiers:
            semantic_match = semantic.get(identifier)
            lexical_match = lexical.get(identifier)
            source = semantic_match[1] if semantic_match else lexical_match[1]
            semantic_rank = semantic_match[0] if semantic_match else None
            bm25_rank = lexical_match[0] if lexical_match else None
            rrf_score = sum(
                1.0 / (self.rrf_c + rank)
                for rank in (semantic_rank, bm25_rank)
                if rank is not None
            )
            delta = max(
                0.0,
                min(
                    MAX_PRIORITY_BOOST,
                    ranking_score(0.0, source["doc_type"], source["metadata"]),
                ),
            )
            fused.append(
                {
                    **source,
                    "metadata": dict(source["metadata"]),
                    "bm25_score": lexical_match[1].get("bm25_score") if lexical_match else None,
                    "semantic_rank": semantic_rank,
                    "bm25_rank": bm25_rank,
                    "semantic_chunk": {
                        "content": semantic_match[1]["content"],
                        "metadata": dict(semantic_match[1]["metadata"]),
                    } if semantic_match else None,
                    "bm25_chunk": {
                        "content": lexical_match[1]["content"],
                        "metadata": dict(lexical_match[1]["metadata"]),
                    } if lexical_match else None,
                    "rrf_score": rrf_score,
                    "metadata_delta": delta,
                    "fused_score": rrf_score * (1.0 + self.metadata_weight * delta),
                }
            )
        return sorted(fused, key=lambda result: result["fused_score"], reverse=True)[:top_k]
