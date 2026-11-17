"""Reality check: run the proposal plan on the repo's real data.

    python -I proposal/feasibility/run_feasibility.py <repo_root> <minilm_onnx_dir> <out_dir>

- Corpus: the four JSON files main ingests, chunked with the repo's own
  rag/structured_chunking.py, embedded with all-MiniLM-L6-v2 (ONNX export,
  mean pooling, L2-normalised, 256 tokens, as sentence-transformers does).
- Retrieval mirrors rag/query.py: cosine similarity, one row per record,
  ranking_score() boost for OliveSoft projects, top_k after sorting.
- For each tender: one query per requirement (requirements matrix) plus the
  tender-level CV and project queries n8n makes (title + issuer + requirements).
- Each deck goes through proposal.compose() exactly as the service would,
  with QueryResult-shaped hits, facts from the source records, and a stand-in
  LLM that fills every prose field to its schema maximum (worst case for
  layout). It is then rendered, validated (overflow, palette, citations) and
  converted to PDF.

No LLM and no web research run here: neither is reachable from this sandbox.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from proposal import render as R  # noqa: E402
from proposal.compose import (TASKS, Trace, bid_warnings, compose,  # noqa: E402
                              evidence_hit, load_records, record_id, retrieved_ids)
from proposal.schemas import PARTIAL_AT, STRONG_AT  # noqa: E402
from proposal.export import to_pdf  # noqa: E402
from proposal.validate import validate  # noqa: E402


class MiniLM:
    def __init__(self, model_dir: Path):
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_length=256)
        self.tok.enable_padding()
        self.sess = ort.InferenceSession(str(model_dir / "model.onnx"),
                                         providers=["CPUExecutionProvider"])

    def embed(self, texts: list[str], batch: int = 64) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i:i + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask,
                     "token_type_ids": np.zeros_like(ids)}
            hidden = self.sess.run(None, feeds)[0]
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            out.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
        return np.vstack(out)


def load_corpus(repo: Path) -> list[dict]:
    """Chunks shaped like the rows rag/ingest_json.py stores."""
    sys.path.insert(0, str(repo))
    from rag.structured_chunking import (chunk_cv_record, chunk_olivesoft_project_record,
                                         chunk_project_record, chunk_tool_record)
    d = repo / "Cvs dataset"
    sources = [("cv", "fake_cvs.json", chunk_cv_record),
               ("project", "fake_projects.json", chunk_project_record),
               ("project", "olivesoft_projects.json", chunk_olivesoft_project_record),
               ("tool", "fake_tools.json", chunk_tool_record)]
    chunks = []
    for doc_type, name, fn in sources:
        data = json.loads((d / name).read_text(encoding="utf-8"))
        data = data if isinstance(data, list) else next(iter(data.values()))
        for rec in data:
            for n, c in enumerate(fn(rec)):
                chunks.append({"id": f"{c['record_id']}:{n}", "doc_type": doc_type,
                               "source_file": name, "content": c["content"],
                               "metadata": {"record_id": c["record_id"], **c["record_meta"]}})
    return chunks, load_records(d)


def search(qvec, chunks, cvecs, doc_type=None, top_k=5):
    """rag/query.py without Supabase: QueryResult rows, one per record,
    sorted by ranking_score then similarity."""
    from rag.ranking import ranking_score
    sims = cvecs @ qvec
    best = {}
    for i in np.argsort(-sims):
        c = chunks[i]
        if doc_type and c["doc_type"] != doc_type:
            continue
        key = (c["doc_type"], c["metadata"]["record_id"])
        if key in best:
            continue
        s = float(sims[i])
        best[key] = {**c, "similarity": s,
                     "ranking_score": ranking_score(s, c["doc_type"], c["metadata"])}
    hits = sorted(best.values(), key=lambda h: (h["ranking_score"], h["similarity"]),
                  reverse=True)
    return hits[:top_k]


def fill(n: int, words="secure scalable integration delivered governed audited platform "
                       "dashboards pipelines migration analytics") -> str:
    """Worst-case prose: realistic words up to exactly n characters."""
    w = words.split()
    out, i = "", 0
    while len(out) + len(w[i % len(w)]) + 1 <= n:
        out = (out + " " + w[i % len(w)]).strip()
        i += 1
    return out.capitalize()


def worst_case_llm(system: str, user: str) -> str:
    """Stands in for the LLM: every field at its schema maximum, four phases
    (the narrowest columns), and citations only to ids it was given."""
    task = next(k for k, v in TASKS.items() if system.endswith(v))
    payload = json.loads(user)
    out = {
        "brief": lambda: {"headline": fill(60), "subtitle": fill(80),
                          "key_messages": [fill(80)] * 3, "tone": fill(80)},
        "letter": lambda: {"salutation": "Dear procurement committee,",
                           "paragraphs": [fill(220), fill(220)],
                           "closing": "We would be glad to walk you through it."},
        "summary": lambda: {"title": fill(53), "why_us": fill(190),
                            "pillars": [{"title": fill(28), "body": fill(110),
                                         "evidence": [a["id"] for a in payload["ASSETS"]][i:i + 1]}
                                        for i in range(3)]},
        "needs": lambda: {"needs": [{"title": fill(40), "body": fill(120)}] * 3},
        "evidence": lambda: {"line": fill(55)},
        "approach": lambda: {"phases": [{"name": fill(20), "weeks": w, "body": fill(100)}
                                        for w in (1, 5, 4, 2)]},
    }[task]()
    return json.dumps(out)


def main(repo: Path, model_dir: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    model = MiniLM(model_dir)
    chunks, records = load_corpus(repo)
    cvecs = model.embed([c["content"] for c in chunks])
    t_index = time.perf_counter() - t0

    feed = repo / "detection" / "data" / "simulated_feed"
    tenders, skipped = [], []
    for f in sorted(feed.glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            skipped.append((f.name, "unreadable file"))
            continue
        if not t.get("requirements"):
            skipped.append((f.name, "no requirements (detection's LLM extracts them)"))
            continue
        tenders.append(t)

    R.apply_theme("website")
    results = []
    for t in tenders:
        reqs = t["requirements"]
        q = model.embed(reqs + [f"{t['title']} {t['issuer']} {' '.join(reqs)}"])
        matches = {req: search(v, chunks, cvecs, top_k=5) for req, v in zip(reqs, q[:-1])}
        cvs = search(q[-1], chunks, cvecs, "cv", 3)
        projects = search(q[-1], chunks, cvecs, "project", 5)
        given = {record_id(h) for hits in [*matches.values(), cvs, projects] for h in hits}

        trace = Trace()
        deck = compose(t, None, matches, cvs, projects, worst_case_llm, records=records,
                       trace=trace, force_bid=True)  # layout stress: write every deck
        pptx = out / f"{t['id']}.pptx"
        t1 = time.perf_counter()
        R.render(deck, str(pptx))
        t_render = time.perf_counter() - t1
        issues = [str(i) for i in validate(str(pptx), deck, given)]
        t2 = time.perf_counter()
        to_pdf(pptx, out)
        t_pdf = time.perf_counter() - t2

        rows = []
        for req, hits in list(matches.items())[:7]:
            top, ev = hits[0], evidence_hit(hits)
            rows.append({"requirement": req, "top_hit": record_id(top),
                         "top_similarity": round(top["similarity"], 3),
                         "evidence_id": ev and record_id(ev),
                         "similarity": ev and round(ev["similarity"], 3),
                         "evidence_text": ev and ev["content"][:160]})
        results.append({
            "tender": t["id"], "issuer": t["issuer"], "title": t["title"], "rows": rows,
            "team": [c.model_dump() for c in deck.team],
            "references": [{"id": r.project_id, "score": r.score, "delivered": r.delivered,
                            "title": r.title} for r in deck.references],
            "llm_steps": len(trace.steps), "citations": sorted(retrieved_ids(deck)),
            "bid_warnings": bid_warnings(deck),
            "render_s": round(t_render, 3), "pdf_s": round(t_pdf, 2), "issues": issues,
        })

    sims = [r["similarity"] for res in results for r in res["rows"] if r["similarity"] is not None]
    summary = {
        "corpus_chunks": len(chunks), "index_seconds": round(t_index, 1),
        "tenders_used": len(results), "skipped": skipped,
        "requirement_rows": sum(len(r["rows"]) for r in results),
        "rows_where_top_hit_was_a_pfe_idea": sum(r["top_hit"] != r["evidence_id"]
                                                 for res in results for r in res["rows"]),
        "evidence_similarity": {"min": round(min(sims), 3),
                                "median": round(statistics.median(sims), 3),
                                "max": round(max(sims), 3)},
        f"labels (Strong >= {STRONG_AT}, Partial >= {PARTIAL_AT})": {
            "Strong": sum(s >= STRONG_AT for s in sims),
            "Partial": sum(PARTIAL_AT <= s < STRONG_AT for s in sims),
            "Gap": sum(s < PARTIAL_AT for s in sims)},
        "references_delivered": sum(r["delivered"] for res in results for r in res["references"]),
        "references_total": sum(len(res["references"]) for res in results),
        "llm_calls_per_deck": {"min": min(r["llm_steps"] for r in results),
                               "max": max(r["llm_steps"] for r in results)},
        "tenders_with_bid_warnings": {r["tender"]: r["bid_warnings"] for r in results
                                      if r["bid_warnings"]},
        "decks_with_validator_issues": sum(bool(r["issues"]) for r in results),
        "render_seconds_median": statistics.median(r["render_s"] for r in results),
        "pdf_seconds_median": statistics.median(r["pdf_s"] for r in results),
    }
    (out / "results.json").write_text(json.dumps({"summary": summary, "tenders": results},
                                                 indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
