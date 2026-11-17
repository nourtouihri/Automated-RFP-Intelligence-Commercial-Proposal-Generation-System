"""Model-free regressions for the isolated lexical/hybrid experiment."""

import json
import math

import pytest

from rag.bm25_retriever import BM25Retriever, tokenize
from rag.doc_types import normalize_doc_type
from rag.evaluate_local import LocalRetriever
from rag.hybrid_retriever import HybridRetriever


def document(record_id, content, doc_type="project", **metadata):
    return {
        "content": content,
        "doc_type": doc_type,
        "metadata": {"record_id": record_id, **metadata},
    }


def record_ids(results):
    return [row["metadata"]["record_id"] for row in results]


def fixed_retriever(rows, calls=None):
    def retrieve(text, *, top_k, doc_type=None):
        if calls is not None:
            calls.append((text, top_k, doc_type))
        return [row for row in rows if not doc_type or row["doc_type"] == doc_type][
            :top_k
        ]

    return retrieve


def test_tokenizer_retains_technical_terms_and_uses_consistent_case():
    assert tokenize(
        "FastAPI PostgreSQL React YOLO n8n ISO 27001 RAG AWS Kubernetes"
    ) == [
        "fastapi", "postgresql", "react", "yolo", "n8n", "iso", "27001",
        "rag", "aws", "kubernetes",
    ]
    assert tokenize(" FASTAPI, PostgreSQL! ") == tokenize("fastapi postgresql")


def test_bm25_exact_technology_terms_retrieve_matching_document():
    retriever = BM25Retriever([
        document("PRJ-REACT", "React frontend application"),
        document("PRJ-API", "FastAPI PostgreSQL backend"),
        document("PRJ-CLOUD", "AWS Kubernetes infrastructure"),
        document("PRJ-VISION", "YOLO image recognition"),
    ])
    matches = retriever("FastAPI PostgreSQL", top_k=5)
    assert record_ids(matches) == ["PRJ-API"]
    assert math.isfinite(matches[0]["bm25_score"])


def test_semantic_synonym_retrieval_is_independent_of_lexical_overlap():
    documents = [
        document("PRJ-CAR", "Automobile fleet diagnostics"),
        document("PRJ-VEGETABLE", "Carrot distribution system"),
    ]
    # Deterministic normalized vectors stand in for model outputs; no download.
    semantic = LocalRetriever(
        documents, [[1.0, 0.0], [0.0, 1.0]],
        query_embedder=lambda _text: [1.0, 0.0],
    )
    assert record_ids(semantic("car maintenance", top_k=2))[0] == "PRJ-CAR"
    assert BM25Retriever(documents)("car maintenance", top_k=2) == []


@pytest.mark.parametrize("query", ["", " ", "\n\t", "!?,..."])
def test_bm25_empty_tokenized_query_returns_no_results(query):
    retriever = BM25Retriever([document("PRJ-1", "FastAPI")])
    assert retriever(query, top_k=5) == []


def test_bm25_handles_empty_corpus_and_empty_tokenized_documents():
    assert BM25Retriever([])("FastAPI", top_k=5) == []
    assert BM25Retriever([
        document("EMPTY", ""), document("PUNCTUATION", "!!!"),
    ])("FastAPI", top_k=5) == []
    matches = BM25Retriever([
        document("EMPTY", ""), document("VALID", "FastAPI PostgreSQL"),
    ])("FastAPI", top_k=5)
    assert record_ids(matches) == ["VALID"]


def test_bm25_keeps_matching_documents_when_bm25_score_is_not_positive():
    # BM25Okapi can assign zero or negative IDF when a term is ubiquitous.
    # Lexical relevance is determined by overlap, not a cosine-style cutoff.
    matches = BM25Retriever([
        document("A", "fastapi"), document("B", "fastapi"),
    ])("fastapi", top_k=5)
    assert set(record_ids(matches)) == {"A", "B"}
    assert all(math.isfinite(row["bm25_score"]) for row in matches)


def test_bm25_highest_scoring_chunk_wins_without_merging_distinct_record_ids():
    retriever = BM25Retriever([
        document("PRJ-01", "FastAPI service"),
        document("PRJ-01", "FastAPI PostgreSQL"),
        document("PRJ-1", "FastAPI PostgreSQL"),
        document("FILL-1", "React frontend"),
        document("FILL-2", "YOLO image recognition"),
        document("FILL-3", "AWS Kubernetes deployment"),
        document("FILL-4", "ISO compliance audit"),
    ])
    results = retriever("FastAPI PostgreSQL", top_k=10)
    assert len(record_ids(results)) == len(set(record_ids(results)))
    assert set(record_ids(results)) == {"PRJ-01", "PRJ-1"}
    best = next(row for row in results if row["metadata"]["record_id"] == "PRJ-01")
    assert best["content"] == "FastAPI PostgreSQL"


def test_original_semantic_retriever_keeps_the_highest_ranked_chunk():
    semantic = LocalRetriever(
        [document("A", "weak chunk"), document("A", "best chunk"),
         document("B", "another record")],
        [[0.6, 0.8], [1.0, 0.0], [0.8, 0.6]],
        query_embedder=lambda _text: [1.0, 0.0],
    )
    results = semantic("unrelated wording", top_k=5)
    assert record_ids(results) == ["A", "B"]
    assert results[0]["content"] == "best chunk"
    assert results[0]["similarity"] == pytest.approx(1.0)


@pytest.mark.parametrize("doc_type", ["cv", "project", "tool", "client"])
def test_all_retrievers_respect_document_type_filter(doc_type):
    documents = [document(kind, "FastAPI React", kind) for kind in ("cv", "project", "tool", "client")]
    semantic = LocalRetriever(
        documents, [[1.0, 0.0]] * len(documents),
        query_embedder=lambda _text: [1.0, 0.0],
    )
    bm25 = BM25Retriever(documents)
    for retriever in (semantic, bm25, HybridRetriever(semantic, bm25)):
        assert record_ids(retriever("FastAPI", top_k=5, doc_type=doc_type)) == [doc_type]


@pytest.mark.parametrize("alias,canonical", [
    ("stack_by_domain", "tool"),
    ("olivesoft_project", "project"),
    ("project_reference", "project"),
    ("client", "client"),
])
def test_document_type_aliases_are_normalized_before_retrieval(alias, canonical):
    assert normalize_doc_type(alias) == canonical
    documents = [document("MATCH", "FastAPI", canonical), document("OTHER", "FastAPI", "cv")]
    bm25 = BM25Retriever(documents)
    calls = []
    semantic = fixed_retriever(documents, calls)
    assert record_ids(bm25("FastAPI", top_k=5, doc_type=alias)) == ["MATCH"]
    assert record_ids(HybridRetriever(semantic, bm25)("FastAPI", top_k=5, doc_type=alias)) == ["MATCH"]
    assert calls[-1][2] == canonical


def test_rrf_merges_both_branches_uses_one_based_ranks_and_preserves_scores():
    a = {**document("A", "semantic-only"), "similarity": 0.99, "ranking_score": 0.99}
    shared_semantic = {**document("B", "semantic passage"), "similarity": 0.8, "ranking_score": 0.8}
    shared_bm25 = {**document("B", "lexical passage"), "bm25_score": 250.0}
    c = {**document("C", "bm25-only"), "bm25_score": 100.0}
    hybrid = HybridRetriever(
        fixed_retriever([a, shared_semantic]), fixed_retriever([shared_bm25, c]),
        rrf_c=60.0,
    )
    results = hybrid("FastAPI", top_k=5)
    assert set(record_ids(results)) == {"A", "B", "C"}
    assert len(results) == 3
    assert record_ids(results)[0] == "B"
    shared = results[0]
    assert shared["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)
    assert shared["semantic_rank"] == 2
    assert shared["bm25_rank"] == 1
    assert shared["similarity"] == pytest.approx(0.8)
    assert shared["bm25_score"] == pytest.approx(250.0)
    assert shared["content"] == "semantic passage"
    assert shared["fused_score"] == pytest.approx(shared["rrf_score"])
    semantic_only = next(row for row in results if row["metadata"]["record_id"] == "A")
    lexical_only = next(row for row in results if row["metadata"]["record_id"] == "C")
    assert semantic_only["bm25_rank"] is None
    assert semantic_only["bm25_score"] is None
    assert lexical_only["semantic_rank"] is None
    assert "similarity" not in lexical_only


def test_rrf_uses_ranks_rather_than_adding_incompatible_raw_scores():
    a = {**document("A", "a"), "similarity": 0.9, "ranking_score": 0.9}
    b = {**document("B", "b"), "bm25_score": 1e12}
    results = HybridRetriever(fixed_retriever([a]), fixed_retriever([b]))("query", top_k=5)
    assert all(row["rrf_score"] == pytest.approx(1 / 61) for row in results)


def test_hybrid_preserves_semantic_results_for_non_latin_query():
    calls = []
    semantic = fixed_retriever([document("AR-1", "متطلبات القطاع")], calls)
    hybrid = HybridRetriever(semantic, fixed_retriever([]))
    assert record_ids(hybrid("متطلبات القطاع", top_k=5)) == ["AR-1"]
    assert len(calls) == 1


def test_hybrid_preserves_each_branches_independent_winning_chunk():
    semantic_row = {**document("A", "semantic chunk", chunk_id="S"), "similarity": 0.8}
    lexical_row = {**document("A", "FastAPI chunk", chunk_id="B"), "bm25_score": 12.0}
    result = HybridRetriever(fixed_retriever([semantic_row]), fixed_retriever([lexical_row]))(
        "FastAPI", top_k=5,
    )[0]
    assert result["semantic_chunk"]["metadata"]["chunk_id"] == "S"
    assert result["bm25_chunk"]["metadata"]["chunk_id"] == "B"
    assert result["semantic_chunk"]["content"] == "semantic chunk"
    assert result["bm25_chunk"]["content"] == "FastAPI chunk"


def test_rrf_deduplicates_duplicate_branch_records_before_assigning_ranks():
    semantic = fixed_retriever([
        document("A", "first chunk"), document("A", "duplicate chunk"), document("B", "b"),
    ])
    hybrid = HybridRetriever(semantic, fixed_retriever([]))
    results = hybrid("query", top_k=5)
    assert record_ids(results) == ["A", "B"]
    assert results[1]["semantic_rank"] == 2


def test_rrf_retrieves_candidate_depth_before_final_top_k():
    calls = []
    semantic = fixed_retriever([document("A", "a")], calls)
    lexical = fixed_retriever([document("B", "b")], calls)
    hybrid = HybridRetriever(semantic, lexical, candidate_depth=20)
    assert len(hybrid("query", top_k=1)) == 1
    assert [call[1] for call in calls] == [20, 20]


def test_zero_metadata_weight_preserves_rrf_and_positive_weight_is_bounded():
    documents = [
        document("A", "external project"),
        document("B", "OliveSoft project", project_origin="olivesoft", matching_priority_boost=1000),
    ]
    semantic = fixed_retriever(documents)
    lexical = fixed_retriever(documents)
    plain = HybridRetriever(semantic, lexical, metadata_weight=0)("query", top_k=5)
    weighted = HybridRetriever(semantic, lexical, metadata_weight=1)("query", top_k=5)
    assert record_ids(plain) == ["A", "B"]
    assert all(row["fused_score"] == pytest.approx(row["rrf_score"]) for row in plain)
    assert record_ids(weighted)[0] == "B"
    for row in weighted:
        assert 0 <= row["metadata_delta"] <= 0.1
        assert row["rrf_score"] <= row["fused_score"] <= row["rrf_score"] * 1.1 + 1e-12


@pytest.mark.parametrize("query", ["", " ", "!!!"])
def test_hybrid_empty_query_does_not_call_either_branch(query):
    def must_not_run(*args, **kwargs):
        raise AssertionError("empty query reached a retriever")

    assert HybridRetriever(must_not_run, must_not_run)(query, top_k=5) == []


@pytest.mark.parametrize("top_k", [0, -1, 1.5, True])
def test_retrievers_reject_invalid_top_k(top_k):
    bm25 = BM25Retriever([document("A", "FastAPI")])
    for retriever in (bm25, HybridRetriever(fixed_retriever([]), bm25)):
        with pytest.raises(ValueError):
            retriever("FastAPI", top_k=top_k)


@pytest.mark.parametrize("kwargs", [
    {"rrf_c": -1}, {"rrf_c": float("nan")},
    {"candidate_depth": 0}, {"candidate_depth": True},
    {"metadata_weight": -0.1}, {"metadata_weight": 1.1},
])
def test_hybrid_rejects_invalid_fusion_configuration(kwargs):
    with pytest.raises(ValueError):
        HybridRetriever(fixed_retriever([]), fixed_retriever([]), **kwargs)


@pytest.mark.parametrize("doc_type", ["", " ", 123])
def test_bm25_and_hybrid_reject_invalid_document_types(doc_type):
    bm25 = BM25Retriever([document("A", "FastAPI")])
    for retriever in (bm25, HybridRetriever(fixed_retriever([]), bm25)):
        with pytest.raises(ValueError):
            retriever("FastAPI", top_k=5, doc_type=doc_type)


def test_ground_truth_validation_reports_missing_and_wrong_type_ids():
    from rag.evaluate_retrieval_variants import validate_ground_truth

    documents = [document("PRJ-1", "FastAPI", "project"), document("CV-1", "React", "cv")]
    cases = [{
        "id": "q1", "query": "FastAPI", "doc_type": "project_reference",
        "relevant_ids": ["PRJ-1", "CV-1", "MISSING"],
    }]
    issues = validate_ground_truth(cases, documents)
    assert len(issues) == 1
    assert issues[0]["case_id"] == "q1"
    assert issues[0]["missing_relevant_ids"] == ["MISSING"]
    assert issues[0]["filtered_out_relevant_ids"] == ["CV-1"]


def test_ground_truth_validation_preserves_exact_record_ids():
    from rag.evaluate_retrieval_variants import validate_ground_truth

    issues = validate_ground_truth(
        [{"id": "q1", "query": "FastAPI", "relevant_ids": ["PRJ-01"]}],
        [document("PRJ-1", "FastAPI")],
    )
    assert issues[0]["missing_relevant_ids"] == ["PRJ-01"]


def test_ndcg_uses_binary_relevance_discount_and_ideal_ranking():
    from rag.evaluate_retrieval_variants import ndcg_at_k

    expected = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(["X", "A", "B"], {"A", "B"}, 3) == pytest.approx(expected)
    assert ndcg_at_k(["A", "B"], {"A", "B"}, 5) == pytest.approx(1)
    assert ndcg_at_k([], {"A"}, 5) == 0


def test_additional_evaluation_metrics_preserve_original_precision_and_recall():
    from rag.evaluate_retrieval_variants import evaluate_variant
    from rag.evaluation import evaluate_cases

    cases = [{"id": "q1", "query": "FastAPI", "doc_type": "project", "relevant_ids": ["A", "B"]}]
    retriever = fixed_retriever([document("X", "irrelevant"), document("A", "FastAPI")])
    original = evaluate_cases(cases, k=5, retriever=retriever)
    extended = evaluate_variant("test", cases, retriever, k=5, latency_repeats=1)
    for key in ("precision_at_k", "recall_at_k", "mean_reciprocal_rank"):
        assert extended[key] == pytest.approx(original[key])


def test_jsonl_loader_preserves_exact_ids_alias_provenance_and_duplicate_chunks(tmp_path):
    from rag.retrieval_corpus import load_jsonl_corpus

    rows = [
        {"id": "chunk-1", "text": "React", "doc_type": "project_reference", "record_id": " PRJ-01 "},
        {"id": "chunk-2", "content": "FastAPI", "doc_type": "olivesoft_project", "metadata": {"record_id": " PRJ-01 "}},
        {"content": "RAG", "doc_type": "stack_by_domain", "metadata": {"record_id": "TOOL-1"}},
        {"content": "Client history", "doc_type": "client", "record_id": "CLIENT-1"},
    ]
    source = tmp_path / "chunks.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    original_bytes = source.read_bytes()
    documents = load_jsonl_corpus(source)
    assert len(documents) == 4
    assert record_ids(documents) == [" PRJ-01 ", " PRJ-01 ", "TOOL-1", "CLIENT-1"]
    assert [row["doc_type"] for row in documents] == ["project", "project", "tool", "client"]
    assert [row["source_doc_type"] for row in documents] == [
        "project_reference", "olivesoft_project", "stack_by_domain", "client",
    ]
    assert documents[0]["content"] == "React"
    assert source.read_bytes() == original_bytes


@pytest.mark.parametrize("row,message", [
    ([], "JSON object"),
    ({"content": 123, "doc_type": "cv", "record_id": "CV-1"}, "content"),
    ({"content": "React", "doc_type": "cv", "metadata": []}, "metadata"),
    ({"id": "chunk-1", "content": "React", "doc_type": "cv"}, "record_id"),
    ({"content": "React", "doc_type": "cv", "record_id": 123}, "record_id"),
    ({"content": "React", "doc_type": "cv", "record_id": "A", "metadata": {"record_id": "B"}}, "conflicting"),
    ({"content": "React", "record_id": "CV-1"}, "doc_type"),
])
def test_jsonl_loader_rejects_malformed_records_without_guessing_identity(tmp_path, row, message):
    from rag.retrieval_corpus import load_jsonl_corpus

    source = tmp_path / "bad.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_jsonl_corpus(source)


def test_jsonl_loader_reports_invalid_json_line_and_empty_corpus(tmp_path):
    from rag.retrieval_corpus import load_jsonl_corpus

    source = tmp_path / "bad.jsonl"
    source.write_text("\n{broken json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r":2: invalid JSON"):
        load_jsonl_corpus(source)
    source.write_text("\n \n", encoding="utf-8")
    with pytest.raises(ValueError, match="no chunks"):
        load_jsonl_corpus(source)


def test_semantic_alias_adapter_preserves_original_scores_and_ranking():
    from rag.retrieval_corpus import CanonicalSemanticRetriever

    local = LocalRetriever(
        [document("A", "external"), document("B", "internal", project_origin="olivesoft", matching_priority_boost=0.08)],
        [[0.9, 0.0], [0.85, 0.0]], query_embedder=lambda _text: [1.0, 0.0],
    )
    original = local("query", top_k=5, doc_type="project")
    adapted = CanonicalSemanticRetriever(local)("query", top_k=5, doc_type="project_reference")
    assert adapted == original
    assert record_ids(adapted) == ["B", "A"]


def test_ndcg_never_counts_a_duplicate_relevant_record_twice():
    from rag.evaluate_retrieval_variants import ndcg_at_k

    assert ndcg_at_k(["A", "A"], {"A"}, 5) == pytest.approx(1)


def test_benchmark_cli_reports_missing_labels_before_loading_model(tmp_path, monkeypatch):
    from rag import evaluate_retrieval_variants as variants

    corpus = tmp_path / "chunks.jsonl"
    corpus.write_text(json.dumps(document("A", "FastAPI")) + "\n", encoding="utf-8")
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps([
        {"id": "q1", "query": "FastAPI", "doc_type": "project", "relevant_ids": ["MISSING"]},
    ]), encoding="utf-8")
    output = tmp_path / "results"
    monkeypatch.setattr("sys.argv", [
        "benchmark", "--chunks", str(corpus), "--dataset", str(dataset),
        "--output-dir", str(output),
    ])

    def must_not_load_model(*args, **kwargs):
        raise AssertionError("invalid ground truth reached model initialization")

    monkeypatch.setattr(variants, "build_retrievers", must_not_load_model)
    assert variants.main() == 2
    validation = json.loads((output / "input_validation.json").read_text(encoding="utf-8"))
    assert validation["case_count"] == 1
    assert validation["issues"][0]["missing_relevant_ids"] == ["MISSING"]
    assert not (output / "semantic_baseline.json").exists()


def test_benchmark_cli_preserves_existing_result_directory(tmp_path, monkeypatch):
    from rag import evaluate_retrieval_variants as variants

    output = tmp_path / "results"
    output.mkdir()
    baseline = output / "semantic_baseline.json"
    baseline.write_text('{"original": true}\n', encoding="utf-8")
    original_bytes = baseline.read_bytes()
    monkeypatch.setattr("sys.argv", ["benchmark", "--output-dir", str(output)])
    with pytest.raises(SystemExit) as error:
        variants.main()
    assert error.value.code == 2
    assert baseline.read_bytes() == original_bytes
