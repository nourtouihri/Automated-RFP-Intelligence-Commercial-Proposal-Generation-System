"""In-memory lexical retrieval over the same chunks as the semantic baseline.

The BM25 index uses global corpus statistics even when a query filters a document
type. Scores are raw BM25 values, not probabilities or cosine similarities.
Only chunks sharing a token with the query are candidates: genuine matches with
zero or negative BM25 scores are retained, while unrelated zero-score records
are excluded. Each exact record ID contributes its highest-scoring chunk.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

from rank_bm25 import BM25Okapi

from rag.doc_types import normalize_doc_type


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase and split on non-alphanumeric characters without stemming.

    Identifiers such as ``n8n`` remain intact; ``ISO 27001`` becomes the two
    literal tokens ``iso`` and ``27001``. Stopwords are deliberately retained.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _TOKEN_PATTERN.findall(text.lower())


def _positive_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _finite_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be a finite number")
    return converted


def record_id(document: dict[str, Any]) -> str:
    """Return the exact corpus ID without stripping or normalizing its value."""
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("document metadata must be an object")
    identifier = metadata.get("record_id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("metadata.record_id must be a non-empty string")
    return identifier


class BM25Retriever:
    """Reusable BM25Okapi chunk index with record-level result deduplication."""

    def __init__(
        self,
        documents: Iterable[dict[str, Any]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ) -> None:
        k1 = _finite_number(k1, "k1")
        b = _finite_number(b, "b")
        epsilon = _finite_number(epsilon, "epsilon")
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        if epsilon < 0:
            raise ValueError("epsilon must be non-negative")

        self.documents: list[dict[str, Any]] = []
        self.tokenized_documents: list[list[str]] = []
        self._token_sets: list[set[str]] = []
        for document in documents:
            if not isinstance(document, dict):
                raise ValueError("each document must be an object")
            if not isinstance(document.get("content"), str):
                raise ValueError("document content must be a string")
            record_id(document)
            doc_type = normalize_doc_type(document.get("doc_type"))
            if doc_type is None:
                raise ValueError("each document must have a document type")
            normalized = {
                **document,
                "doc_type": doc_type,
                "metadata": dict(document["metadata"]),
            }
            tokens = tokenize(normalized["content"])
            self.documents.append(normalized)
            self.tokenized_documents.append(tokens)
            self._token_sets.append(set(tokens))

        # BM25Okapi divides by corpus length and average document length. An
        # empty corpus or a corpus containing only empty documents has no index.
        self.index = (
            BM25Okapi(self.tokenized_documents, k1=k1, b=b, epsilon=epsilon)
            if any(self.tokenized_documents)
            else None
        )

    def __call__(
        self, text: str, *, top_k: int, doc_type: str | None = None
    ) -> list[dict[str, Any]]:
        _positive_integer(top_k, "top_k")
        doc_type = normalize_doc_type(doc_type)
        query_tokens = tokenize(text)
        if not query_tokens or self.index is None:
            return []

        scores = self.index.get_scores(query_tokens)
        query_token_set = set(query_tokens)
        best_by_record: dict[str, tuple[int, dict[str, Any]]] = {}
        for index, (document, tokens, raw_score) in enumerate(
            zip(self.documents, self._token_sets, scores)
        ):
            if doc_type is not None and document["doc_type"] != doc_type:
                continue
            if not query_token_set.intersection(tokens):
                continue
            identifier = record_id(document)
            score = float(raw_score)
            previous = best_by_record.get(identifier)
            if previous is None or score > previous[1]["bm25_score"]:
                best_by_record[identifier] = (
                    index,
                    {**document, "metadata": dict(document["metadata"]), "bm25_score": score},
                )

        # Preserve corpus order for equal-scoring chunks/records on every run.
        ordered = sorted(
            best_by_record.values(), key=lambda item: (-item[1]["bm25_score"], item[0])
        )
        return [result for _, result in ordered[:top_k]]
