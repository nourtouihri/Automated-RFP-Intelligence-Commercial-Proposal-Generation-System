"""Query one isolated local retrieval variant without a database or API keys.

Examples::

    python -m rag.retrieve_local --bundled --variant bm25 \\
        --query "FastAPI PostgreSQL n8n" --doc-type project --top-k 5
    python -m rag.retrieve_local --chunks "Cvs dataset/all_chunks.fixed.jsonl" \\
        --variant hybrid --query "ISO 27001 security compliance" --doc-type tool

BM25-only retrieval never initializes the embedding model or imports torch.
Semantic/hybrid variants use the unchanged baseline and shared benchmark setup.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from rag.doc_types import normalize_doc_type
from rag.retrieval_corpus import load_bundled_corpus, load_jsonl_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--chunks", type=Path, help="read-only canonical JSONL corpus")
    source.add_argument("--bundled", action="store_true", help="explicitly use the bundled source corpus")
    parser.add_argument(
        "--variant", choices=("semantic", "bm25", "hybrid", "hybrid-metadata"), default="bm25"
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--doc-type", help="optional canonical type or documented alias")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rrf-c", type=float, default=60.0)
    parser.add_argument("--candidate-depth", type=int, default=20)
    parser.add_argument("--metadata-weight", type=float, default=0.5)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()
    if not args.query.strip():
        parser.error("--query must contain non-whitespace text")
    if args.top_k < 1 or args.candidate_depth < 1 or args.threads < 1:
        parser.error("--top-k, --candidate-depth and --threads must be positive")
    if not math.isfinite(args.rrf_c) or args.rrf_c < 0:
        parser.error("--rrf-c must be finite and non-negative")
    if not math.isfinite(args.metadata_weight) or not 0 <= args.metadata_weight <= 1:
        parser.error("--metadata-weight must be finite and between 0 and 1")
    if args.variant.startswith("hybrid") and args.candidate_depth < args.top_k:
        parser.error("--candidate-depth must be at least --top-k for hybrid retrieval")

    chunks_path = args.chunks or Path("Cvs dataset/all_chunks.fixed.jsonl")
    try:
        doc_type = normalize_doc_type(args.doc_type)
        documents = load_bundled_corpus() if args.bundled else load_jsonl_corpus(chunks_path)
        # Import inside the guarded path so missing optional dependencies result
        # in a useful command-line error rather than an import-time traceback.
        from rag.bm25_retriever import BM25Retriever
        from rag.evaluate_retrieval_variants import _debug_match

        if args.variant == "bm25":
            retriever = BM25Retriever(documents)
        else:
            import torch

            from rag.evaluate_retrieval_variants import build_retrievers

            torch.manual_seed(0)
            torch.set_num_threads(args.threads)
            torch.use_deterministic_algorithms(True)
            retrievers, _ = build_retrievers(
                documents,
                rrf_c=args.rrf_c,
                candidate_depth=args.candidate_depth,
                metadata_weight=args.metadata_weight,
            )
            variant_names = {
                "semantic": "semantic_baseline",
                "hybrid": "hybrid_rrf",
                "hybrid-metadata": "hybrid_metadata",
            }
            retriever = retrievers[variant_names[args.variant]]
        matches = retriever(args.query, top_k=args.top_k, doc_type=doc_type)
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        parser.error(str(exc))

    print(json.dumps(
        {
            "variant": args.variant,
            "query": args.query,
            "doc_type": doc_type,
            "top_k": args.top_k,
            "corpus_chunks": len(documents),
            "corpus_mode": "bundled_source_records" if args.bundled else "canonical_jsonl",
            "configuration": {
                "rrf_c": args.rrf_c,
                "candidate_depth": args.candidate_depth,
                "metadata_weight": args.metadata_weight if args.variant == "hybrid-metadata" else 0.0,
                "threads": args.threads,
            },
            "matches": [_debug_match(match) for match in matches],
        },
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
