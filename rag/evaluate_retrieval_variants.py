"""Fair offline comparison of unchanged semantic retrieval, BM25 and RRF."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
from statistics import mean
import subprocess
import sys
from time import perf_counter
from typing import Callable

from rag.bm25_retriever import BM25Retriever
from rag.doc_types import normalize_doc_type
from rag.embeddings import DEFAULT_EMBEDDING_MODEL, embed_batch
from rag.evaluate_local import LocalRetriever
from rag.evaluation import evaluate_cases, load_cases, precision_at_k, recall_at_k, reciprocal_rank
from rag.hybrid_retriever import HybridRetriever
from rag.retrieval_corpus import CanonicalSemanticRetriever, load_bundled_corpus, load_jsonl_corpus


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Binary relevance; repeated IDs receive gain only at their first rank."""
    if k < 1 or not relevant:
        raise ValueError("k must be positive and relevant IDs must not be empty")
    seen: set[str] = set()
    dcg = 0.0
    for rank, record_id in enumerate(retrieved[:k], 1):
        if record_id in relevant and record_id not in seen:
            dcg += 1.0 / math.log2(rank + 1)
        seen.add(record_id)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return dcg / ideal


def validate_ground_truth(cases: list[dict], documents: list[dict]) -> list[dict]:
    """Return every missing/inaccessible label; never silently skip a case."""
    if not cases:
        raise ValueError("benchmark must contain at least one case")
    by_id: dict[str, set[str]] = {}
    for document in documents:
        record_id = document["metadata"]["record_id"]
        by_id.setdefault(record_id, set()).add(normalize_doc_type(document["doc_type"]))
    issues = []
    seen_cases = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("every evaluation case must be a JSON object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_cases:
            raise ValueError("every evaluation case must have a unique non-empty string id")
        seen_cases.add(case_id)
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"case {case_id!r} must contain a non-empty query")
        labels = case.get("relevant_ids")
        if not isinstance(labels, list) or not labels or any(
            not isinstance(value, str) or not value.strip() for value in labels
        ):
            raise ValueError(f"case {case_id!r} must contain non-empty string relevant_ids")
        doc_type = normalize_doc_type(case.get("doc_type"))
        missing = sorted(set(labels) - by_id.keys())
        filtered = sorted({
            label for label in labels
            if label in by_id and doc_type is not None and doc_type not in by_id[label]
        })
        if missing or filtered:
            issues.append({
                "case_id": case_id,
                "missing_relevant_ids": missing,
                "filtered_out_relevant_ids": filtered,
            })
    return issues


def _retrieve(retriever: Callable, case: dict, k: int) -> list[dict]:
    return retriever(case["query"], top_k=k, doc_type=normalize_doc_type(case.get("doc_type")))


def _ids(matches: list[dict]) -> list[str]:
    return [match["metadata"]["record_id"] for match in matches]


def _debug_match(match: dict) -> dict:
    """Persist diagnostic scores and the winning chunk, never vectors."""
    fields = (
        "similarity", "ranking_score", "semantic_score", "bm25_score",
        "semantic_rank", "bm25_rank", "rrf_score", "metadata_delta", "fused_score",
        "semantic_chunk", "bm25_chunk",
    )
    return {
        "record_id": match["metadata"]["record_id"],
        "doc_type": match["doc_type"],
        "content": match["content"],
        "metadata": match["metadata"],
        **{key: match[key] for key in fields if key in match},
    }


def evaluate_variant(
    name: str, cases: list[dict], retriever: Callable, *, k: int = 5, latency_repeats: int = 3,
) -> dict:
    """Use original P/R/RR definitions, adding binary nDCG, P/R@10 and latency."""
    if k < 1 or latency_repeats < 1 or not cases:
        raise ValueError("k, latency_repeats and number of cases must be positive")
    normalized_cases = [{**case, "doc_type": normalize_doc_type(case.get("doc_type"))} for case in cases]
    # Deliberately reuse the baseline evaluator instead of reimplementing metrics.
    report = evaluate_cases(normalized_cases, k=k, retriever=retriever)
    details = []
    for case, original in zip(normalized_cases, report["cases"]):
        matches = _retrieve(retriever, case, k)
        retrieved = _ids(matches)
        if retrieved != original["retrieved_ids"]:
            raise ValueError(f"retrieval is not deterministic for case {case['id']!r}")
        ten_matches = _retrieve(retriever, case, 10)
        times = []
        # Warm queries; excludes model load, corpus embedding, indexing and file I/O.
        for _ in range(latency_repeats):
            start = perf_counter()
            timed = _retrieve(retriever, case, k)
            times.append((perf_counter() - start) * 1000)
            if _ids(timed) != retrieved:
                raise ValueError(f"retrieval is not deterministic for case {case['id']!r}")
        relevant = set(case["relevant_ids"])
        details.append({
            **original,
            "query": case["query"],
            "doc_type": case.get("doc_type"),
            "relevant_ids": case["relevant_ids"],
            "ndcg_at_k": ndcg_at_k(retrieved, relevant, k),
            "precision_at_10": precision_at_k(_ids(ten_matches), relevant, 10),
            "recall_at_10": recall_at_k(_ids(ten_matches), relevant, 10),
            "retrieved_ids_at_10": _ids(ten_matches),
            "latency_ms": mean(times),
            "latency_samples_ms": times,
            "matches": [_debug_match(match) for match in matches],
        })
    return {
        **report,
        "variant": name,
        "ndcg_at_k": mean(item["ndcg_at_k"] for item in details),
        "precision_at_10": mean(item["precision_at_10"] for item in details),
        "recall_at_10": mean(item["recall_at_10"] for item in details),
        "empty_result_rate": mean(not item["retrieved_ids"] for item in details),
        "average_latency_ms": mean(item["latency_ms"] for item in details),
        "latency_repeats": latency_repeats,
        "latency_scope": "warm serial retrieval including query embedding; excludes initialization and I/O",
        "skipped_cases": [],
        "missing_relevant_ids": [],
        "cases": details,
    }


def build_retrievers(documents: list[dict], *, rrf_c: float, candidate_depth: int, metadata_weight: float):
    """Share one embedding matrix and one BM25 index across the four variants."""
    semantic_start = perf_counter()
    # The embedding API rejects empty text. Preserve empty chunks in the corpus,
    # but give them a zero vector instead of calling the model with invalid input.
    nonempty = [index for index, doc in enumerate(documents) if doc["content"].strip()]
    embedded = embed_batch([documents[index]["content"] for index in nonempty])
    dimensions = len(embedded[0]) if embedded else 384
    vectors = [[0.0] * dimensions for _ in documents]
    for index, vector in zip(nonempty, embedded):
        vectors[index] = vector
    semantic = CanonicalSemanticRetriever(LocalRetriever(documents, vectors))
    semantic_setup = (perf_counter() - semantic_start) * 1000
    lexical_start = perf_counter()
    lexical = BM25Retriever(documents)
    lexical_setup = (perf_counter() - lexical_start) * 1000
    return {
        "semantic_baseline": semantic,
        "bm25_only": lexical,
        "hybrid_rrf": HybridRetriever(semantic, lexical, rrf_c=rrf_c, candidate_depth=candidate_depth),
        "hybrid_metadata": HybridRetriever(
            semantic, lexical, rrf_c=rrf_c, candidate_depth=candidate_depth,
            metadata_weight=metadata_weight,
        ),
    }, {"semantic_setup_ms": semantic_setup, "bm25_setup_ms": lexical_setup}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    # Exclusive create protects existing baseline/results even on accidental reruns.
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def _runtime() -> dict:
    packages = {}
    for name in ("rank-bm25", "sentence-transformers", "torch", "numpy", "transformers"):
        packages[name] = importlib.metadata.version(name)
    return {"python": sys.version, "platform": platform.platform(), "packages": packages}


def _comparison(reports: dict[str, dict]) -> dict:
    base = {case["id"]: case for case in reports["semantic_baseline"]["cases"]}
    metrics = (
        "precision_at_k", "recall_at_k", "mean_reciprocal_rank", "ndcg_at_k",
        "precision_at_10", "recall_at_10", "empty_result_rate", "average_latency_ms",
    )
    variants = {}
    for name, report in reports.items():
        deltas = []
        for case in report["cases"]:
            before = base[case["id"]]
            rr_delta = case["reciprocal_rank"] - before["reciprocal_rank"]
            recall_delta = case["recall_at_k"] - before["recall_at_k"]
            ndcg_delta = case["ndcg_at_k"] - before["ndcg_at_k"]
            if rr_delta or recall_delta or ndcg_delta:
                deltas.append({
                    "id": case["id"], "query": case["query"],
                    "baseline_retrieved_ids": before["retrieved_ids"],
                    "retrieved_ids": case["retrieved_ids"],
                    "reciprocal_rank_delta": rr_delta, "recall_delta": recall_delta,
                    "ndcg_delta": ndcg_delta,
                })
        variants[name] = {**{key: report[key] for key in metrics}, "case_changes_vs_semantic": deltas}
    # Report an explicit selection policy, not an unsupported claim of universal superiority.
    key = lambda name: (
        reports[name]["recall_at_k"], reports[name]["ndcg_at_k"],
        reports[name]["mean_reciprocal_rank"], reports[name]["precision_at_k"],
    )
    best_quality = max(key(name) for name in reports)
    winners = [name for name in reports if key(name) == best_quality]
    return {
        "selection_policy": "maximize Recall@K, then nDCG@K, MRR@K and Precision@K; ties retained",
        "best_quality_variants": winners,
        "fastest_among_best_quality": min(winners, key=lambda name: reports[name]["average_latency_ms"]),
        "variants": variants,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--chunks", type=Path, help="read-only canonical JSONL corpus")
    source.add_argument("--bundled", action="store_true", help="explicitly use the existing 127-chunk source corpus")
    parser.add_argument("--dataset", type=Path, default=Path("rag/eval_dataset.json"))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--rrf-c", type=float, default=60.0)
    parser.add_argument("--candidate-depth", type=int, default=20)
    parser.add_argument("--metadata-weight", type=float, default=0.5)
    parser.add_argument("--latency-repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("rag/benchmarks"))
    parser.add_argument("--expected-cases", type=int)
    parser.add_argument("--expected-chunks", type=int)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()
    if (
        args.k < 1 or args.latency_repeats < 1 or args.threads < 1
        or args.candidate_depth < max(args.k, 10)
        or not math.isfinite(args.rrf_c) or args.rrf_c < 0
        or not 0 <= args.metadata_weight <= 1
    ):
        parser.error("positive k/repeats/threads, candidate-depth >= max(k,10), c >= 0 and weight in [0,1] required")
    if args.output_dir.exists() and (
        not args.output_dir.is_dir() or any(args.output_dir.iterdir())
    ):
        parser.error(f"{args.output_dir} is not empty; choose a new --output-dir to preserve existing results")
    chunks_path = args.chunks or Path("Cvs dataset/all_chunks.fixed.jsonl")
    try:
        documents = load_bundled_corpus() if args.bundled else load_jsonl_corpus(chunks_path)
        cases = load_cases(args.dataset)
        issues = validate_ground_truth(cases, documents)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    mismatches = []
    for name, expected, observed in (
        ("cases", args.expected_cases, len(cases)), ("chunks", args.expected_chunks, len(documents)),
    ):
        if expected is not None and expected != observed:
            mismatches.append({"kind": name, "expected": expected, "observed": observed})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    validation = {"case_count": len(cases), "corpus_chunks": len(documents), "issues": issues, "count_mismatches": mismatches}
    _write_json(args.output_dir / "input_validation.json", validation)
    if issues or mismatches:
        print(json.dumps(validation, indent=2))
        print("Ground truth/count validation failed; no cases skipped or labels changed.", file=sys.stderr)
        return 2

    import torch
    torch.manual_seed(0)
    torch.set_num_threads(args.threads)
    torch.use_deterministic_algorithms(True)
    retrievers, setup = build_retrievers(
        documents, rrf_c=args.rrf_c, candidate_depth=args.candidate_depth, metadata_weight=args.metadata_weight,
    )
    source_paths = [chunks_path] if not args.bundled else [
        Path("Cvs dataset") / name for name in
        ("fake_cvs.json", "fake_projects.json", "fake_tools.json", "olivesoft_projects.json")
    ]
    paths = [*source_paths, args.dataset]
    implementation_paths = [
        Path("rag") / name for name in (
            "evaluate_local.py", "evaluation.py", "embeddings.py", "ranking.py",
            "doc_types.py", "retrieval_corpus.py", "bm25_retriever.py",
            "hybrid_retriever.py", "evaluate_retrieval_variants.py",
        )
    ]
    hashes_before = {str(path): _sha256(path) for path in paths}
    # Unmodified evaluator/semantic scoring provides an independent metric reference.
    baseline = evaluate_cases(cases, k=args.k, retriever=retrievers["semantic_baseline"])
    baseline["corpus_chunks"] = len(documents)
    _write_json(args.output_dir / "original_semantic_baseline.json", baseline)
    reports = {}
    for name, retriever in retrievers.items():
        report = evaluate_variant(name, cases, retriever, k=args.k, latency_repeats=args.latency_repeats)
        report["corpus_chunks"] = len(documents)
        reports[name] = report
        _write_json(args.output_dir / f"{name}.json", report)
    for metric in ("precision_at_k", "recall_at_k", "mean_reciprocal_rank"):
        if reports["semantic_baseline"][metric] != baseline[metric]:
            raise RuntimeError(f"semantic baseline metric changed: {metric}")
    if hashes_before != {str(path): _sha256(path) for path in paths}:
        raise RuntimeError("input files changed during the experiment")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": commit,
        "corpus_mode": "bundled_source_records" if args.bundled else "canonical_jsonl",
        "case_count": len(cases), "corpus_chunks": len(documents), "k": args.k,
        "document_types": dict(Counter(doc["doc_type"] for doc in documents)),
        "input_sha256": hashes_before,
        "implementation_sha256": {str(path): _sha256(path) for path in implementation_paths},
        "configuration": {
            "rrf_c": args.rrf_c, "candidate_depth": args.candidate_depth,
            "metadata_weight": args.metadata_weight, "threads": args.threads,
            "embedding_model": os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
            "normalize_embeddings": True, "bm25_k1": 1.5, "bm25_b": 0.75, "bm25_epsilon": 0.25,
            "tokenizer": "lowercase alphanumeric [a-z0-9]+, no stemming or stopword removal",
        },
        "runtime": _runtime(), "setup": setup,
        "metric_definitions": {
            "precision_at_k": "unique retrieved relevant IDs / fixed k, including short result lists",
            "recall_at_k": "unique retrieved relevant IDs / number of relevant IDs",
            "mean_reciprocal_rank": "macro mean reciprocal rank of first relevant result within top k",
            "ndcg_at_k": "binary DCG / ideal DCG; discount log2(rank+1)",
            "aggregation": "unweighted macro mean across every case; none skipped",
        },
        "skipped_cases": [], "missing_relevant_ids": [], "baseline_metrics_preserved": True,
        "limitations": [
            *([
                "The requested 543-chunk / 21-case files were not available in the supplied repositories.",
                "These bundled results do not verify the user-supplied 543-chunk baseline.",
            ] if args.bundled else [
                "Corpus provided explicitly; verify its hashes against the intended canonical inputs.",
                "Empty-content chunks receive zero vectors; original source-record corpora contain no such chunks.",
            ]),
            "The semantic branch of both hybrids retains its original metadata-aware ranking.",
            "Latency uses warm serial queries on one machine; no production throughput claim.",
            "No embedding cache: hybrid latency includes a semantic query embedding.",
            "Relevance labels are sparse and this dataset is too small to establish general superiority.",
        ],
        **_comparison(reports),
    }
    _write_json(args.output_dir / "comparison_summary.json", summary)
    print(json.dumps({
        "output_dir": str(args.output_dir), "case_count": len(cases), "corpus_chunks": len(documents),
        "best_quality_variants": summary["best_quality_variants"],
        "variants": {name: {key: value for key, value in row.items() if key != "case_changes_vs_semantic"}
                     for name, row in summary["variants"].items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
