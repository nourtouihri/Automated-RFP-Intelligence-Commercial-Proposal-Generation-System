"""Task 3: check the fix/data-rag corpus with the generator's own code, nothing merged.

    python -X utf8 proposal/feasibility/data_rag_check.py <worktree_of_fix_data_rag> <out.json>

The worktree is read-only input. The corpus is rag_ready/all_chunks.fixed.jsonl (543 chunks), turned
into the rows the branch's rag/ingest_json.py would store (metadata.record_id = the chunk id,
doc_type mapped through rag/doc_types.py), embedded with this repo's rag.embeddings, and searched the
way rag/query.py does (best chunk per record, ranking_score, top_k). Compares:

- record ids: do the chunk ids match the source records compose.load_records reads?
- calibration: Strong / Partial / Gap against ground_truth.json (relevant cv_ids and project_ids per
  tender, and its list of uncovered requirements)
- what the missing project_origin key does to the OliveSoft ranking boost
- the 14 simulated and 5 held-out tenders on this corpus
"""

from __future__ import annotations

import collections
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

from proposal.compose import (PARTIAL_AT, STRONG_AT, InputError, compose, evidence_hit,  # noqa: E402
                              is_delivered, is_idea, is_record, load_records, record_id)
from proposal.schemas import NoBid  # noqa: E402
from rag.embeddings import embed_batch  # noqa: E402
from rag.ranking import ranking_score  # noqa: E402

WT = Path(sys.argv[1])
DATA = WT / "Cvs dataset"
FILES = ("cvs_clean.json", "projects_clean.json", "olivesoft_projects.json", "client_portfolio.json",
         "tech_stacks.json")


def doc_type_overrides() -> dict:
    spec = importlib.util.spec_from_file_location("wt_doc_types", WT / "rag" / "doc_types.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DOC_TYPE_OVERRIDES


class Corpus:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.vecs = np.array(embed_batch([r["content"] for r in rows]))

    def search(self, text: str, top_k: int = 5, doc_type: str | None = None) -> list[dict]:
        sims = self.vecs @ np.array(embed_batch([text])[0])
        best = {}
        for i in np.argsort(-sims):
            r = self.rows[i]
            if doc_type and r["doc_type"] != doc_type:
                continue
            key = (r["doc_type"], r["metadata"]["record_id"])
            if key not in best:
                s = float(sims[i])
                best[key] = {**r, "similarity": s,
                             "ranking_score": ranking_score(s, r["doc_type"], r["metadata"])}
        hits = sorted(best.values(), key=lambda h: (h["ranking_score"], h["similarity"]), reverse=True)
        return hits[:top_k]


def load_rows() -> tuple[list[dict], list[dict]]:
    chunks = [json.loads(line) for line in
              (DATA / "rag_ready" / "all_chunks.fixed.jsonl").read_text(encoding="utf-8").splitlines()]
    over = doc_type_overrides()
    rows = [{"id": c["id"], "content": c["text"], "doc_type": over.get(c["doc_type"], c["doc_type"]),
             "source_file": c.get("source_file", ""),
             "metadata": {**c.get("metadata", {}), "record_id": c["id"], "original_doc_type": c["doc_type"]}}
            for c in chunks]
    return chunks, rows


def feed(path: Path) -> list[dict]:
    return [t for t in (json.loads(f.read_text(encoding="utf-8")) for f in sorted(path.glob("*.json")))
            if t.get("requirements")]


def band(score: float) -> str:
    return "Strong" if score >= STRONG_AT else "Partial" if score >= PARTIAL_AT else "Gap"


def main(out_path: Path) -> None:
    chunks, rows = load_rows()
    corpus = Corpus(rows)
    records = load_records(DATA, files=FILES)
    out = {"worktree_commit": os.popen(f'git -C "{WT}" rev-parse --short HEAD').read().strip()}

    # ---- record ids
    by_type = collections.defaultdict(lambda: [0, 0])
    unmatched = collections.defaultdict(list)
    for c in chunks:
        by_type[c["doc_type"]][0] += 1
        if c["id"] in records:
            by_type[c["doc_type"]][1] += 1
        else:
            unmatched[c["doc_type"]].append(c["id"])
    out["record_ids"] = {
        "chunks": len(chunks), "chunk_has_metadata_record_id": sum("record_id" in c.get("metadata", {}) for c in chunks),
        "unique_ids": len({c["id"] for c in chunks}),
        "matched_by_doc_type": {t: {"chunks": n, "in_source_records": m} for t, (n, m) in by_type.items()},
        "unmatched_examples": {t: ids[:3] for t, ids in unmatched.items()},
        "review_needed": json.loads((DATA / "rag_ready" / "review_needed.json").read_text(encoding="utf-8"))
        if (DATA / "rag_ready" / "review_needed.json").exists() else None}
    rn = out["record_ids"]["review_needed"]
    out["record_ids"]["review_needed"] = {k: (len(v) if isinstance(v, list) else v) for k, v in rn.items()} \
        if isinstance(rn, dict) else rn

    # ---- projects: is there a usable status
    projects = json.loads((DATA / "projects_clean.json").read_text(encoding="utf-8"))
    out["projects"] = {
        "n": len(projects), "fields": sorted({k for p in projects for k in p}),
        "has_status_field": any("status" in p or "is_completed" in p for p in projects),
        "outcome_null": sum(p["outcome"] is None for p in projects),
        "synthetic": sum(bool(p.get("synthetic")) for p in projects),
        "delivered_by_the_outcome_rule": sum(is_delivered(p) for p in projects),
        "outcome_openers": collections.Counter(" ".join(p["outcome"].split()[:2]) for p in projects if p["outcome"]).most_common(6)}
    ideas = [r for r in rows if r["metadata"]["original_doc_type"] == "olivesoft_project"]
    out["ideas"] = {"chunks": len(ideas), "have_project_origin": sum("project_origin" in r["metadata"] for r in ideas),
                    "have_relationship": sum("relationship" in r["metadata"] for r in ideas),
                    "recognised_as_ideas": sum(is_idea(r["metadata"]) for r in ideas),
                    "boost_on_main": 0.08, "boost_here": max(
                        (ranking_score(0.5, r["doc_type"], r["metadata"]) - 0.5 for r in ideas), default=0)}

    # ---- calibration against ground_truth.json
    gt = json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))
    sim = {t["id"]: t for t in feed(REPO / "detection" / "data" / "simulated_feed")}
    rows_out, tender_level, overlap_miss = [], [], []
    for tid, truth in gt.items():
        if tid not in sim:
            continue
        t = sim[tid]
        relevant = set(truth["cv_ids"]) | set(truth["project_ids"])
        unc = set(truth["uncovered_requirements"])
        overlap_miss += [u for u in unc if u not in t["requirements"]]
        # the file words its uncovered requirements differently from the feed: map each to the
        # closest feed requirement of the same tender by embedding similarity
        fuzzy = {}
        if unc:
            ev, rv = np.array(embed_batch(sorted(unc))), np.array(embed_batch(t["requirements"]))
            for u, row in zip(sorted(unc), ev @ rv.T):
                j = int(np.argmax(row))
                fuzzy[t["requirements"][j]] = (u, round(float(row[j]), 2))
        for req in t["requirements"]:
            hits = corpus.search(req, top_k=5)
            ev = evidence_hit(hits)
            score = round(ev["similarity"], 2) if ev else 0.0
            rows_out.append({"top1_is_idea": is_idea(hits[0]["metadata"]),"tender": tid, "requirement": req, "score": score, "uncovered": req in fuzzy or req in unc,
                             "uncovered_as_worded": fuzzy.get(req, (None, None))[0], "uncovered_match_sim": fuzzy.get(req, (None, None))[1],
                             "top_is_relevant": bool(ev and record_id(ev) in relevant),
                             "relevant_in_top5": any(record_id(h) in relevant for h in hits),
                             "top_type": ev["metadata"]["original_doc_type"] if ev else None})
        q = "\n".join([t["title"], t["issuer"], *t["requirements"]])
        cvs, prj = corpus.search(q, 3, "cv"), corpus.search(q, 5, "project")
        tender_level.append({"tender": tid, "cv_recall_at_3": len({record_id(h) for h in cvs} & set(truth["cv_ids"])) / max(1, len(truth["cv_ids"])),
                             "project_recall_at_5": len({record_id(h) for h in prj} & set(truth["project_ids"])) / max(1, len(truth["project_ids"])),
                             "project_top5_types": [h["metadata"]["original_doc_type"] for h in prj],
                             "project_top5_are_PRJ": sum(record_id(h).startswith("PRJ-") for h in prj)})
    out["ground_truth"] = {"tenders_in_file": len(gt), "tenders_used": len({r["tender"] for r in rows_out}),
                           "uncovered_not_found_in_feed": overlap_miss, "rows": len(rows_out),
                           "uncovered_rows": sum(r["uncovered"] for r in rows_out)}
    bands = {}
    for b in ("Strong", "Partial", "Gap"):
        sel = [r for r in rows_out if band(r["score"]) == b]
        cov = [r for r in sel if not r["uncovered"]]
        bands[b] = {"rows": len(sel), "uncovered_rows": len(sel) - len(cov),
                    "covered_top_is_relevant": sum(r["top_is_relevant"] for r in cov), "covered_rows": len(cov),
                    "covered_but_relevant_in_top5": sum(r["relevant_in_top5"] for r in cov)}
    out["bands"] = bands
    out["top_type_by_band"] = {b: dict(collections.Counter(r["top_type"] for r in rows_out if band(r["score"]) == b)) for b in ("Strong", "Partial", "Gap")}
    out["uncovered_mapping"] = [(r["tender"], r["requirement"], r["uncovered_as_worded"], r["uncovered_match_sim"], r["score"]) for r in rows_out if r["uncovered"]]
    sweep = []
    for th in [round(0.30 + 0.05 * i, 2) for i in range(9)]:
        above = [r for r in rows_out if r["score"] >= th]
        below = [r for r in rows_out if r["score"] < th]
        sweep.append({"threshold": th, "rows_at_or_above": len(above),
                      "right_asset_share_at_or_above": round(sum((not r["uncovered"]) and r["top_is_relevant"] for r in above) / max(1, len(above)), 2),
                      "rows_below": len(below),
                      "uncovered_share_below": round(sum(r["uncovered"] for r in below) / max(1, len(below)), 2),
                      "covered_rows_with_a_relevant_hit_in_top5_below": sum((not r["uncovered"]) and r["relevant_in_top5"] for r in below)})
    out["sweep"] = sweep
    out["tender_level"] = tender_level
    out["ideas_top1"] = {"rows": len(rows_out), "top1_is_an_idea": sum(r["top1_is_idea"] for r in rows_out),
                         "main_corpus_reported": "19 of 53 rows (feasibility-report.md)"}
    cards = []
    for tid, t in sim.items():
        q = "\n".join([t["title"], t["issuer"], *t["requirements"]])
        prj = [h for h in corpus.search(q, 5, "project") if is_record(h, "project") or is_idea(h["metadata"])]
        prj = sorted(prj, key=lambda h: not is_delivered({**h["metadata"], **records.get(record_id(h), {})}))[:3]
        for h in prj:
            rec = {**h["metadata"], **records.get(record_id(h), {})}
            cards.append({"tender": tid, "id": record_id(h), "type": h["metadata"]["original_doc_type"],
                          "has_source_record": record_id(h) in records,
                          "title": rec.get("name") or rec.get("summary") or record_id(h),
                          "title_is_just_the_id": (rec.get("name") or rec.get("summary") or record_id(h)) == record_id(h),
                          "delivered": is_delivered(rec), "is_idea": is_idea(rec)})
    out["reference_cards"] = {"cards": len(cards), "not_a_PRJ_record": sum(not c["id"].startswith("PRJ-") for c in cards),
                              "no_source_record": sum(not c["has_source_record"] for c in cards),
                              "title_is_just_the_id": sum(c["title_is_just_the_id"] for c in cards),
                              "delivered": sum(c["delivered"] for c in cards), "ideas": sum(c["is_idea"] for c in cards),
                              "by_type": dict(collections.Counter(c["type"] for c in cards)),
                              "examples_without_record": [c for c in cards if not c["has_source_record"]][:4]}
    out["rows_detail"] = rows_out

    # ---- the 19 tenders on this corpus
    class Called(Exception):
        pass

    def llm(system, user):
        raise Called()
    tenders = [("simulated", t) for t in feed(REPO / "detection" / "data" / "simulated_feed")] + \
              [("held-out", t) for t in feed(HERE / "heldout")]
    scores, verdicts = [], []
    for kind, t in tenders:
        matches = {r: corpus.search(r, 5) for r in t["requirements"]}
        q = "\n".join([t["title"], t["issuer"], *t["requirements"]])
        cvs, prj = corpus.search(q, 3, "cv"), corpus.search(q, 5, "project")
        sc = [round(evidence_hit(h)["similarity"], 2) if evidence_hit(h) else 0.0 for h in matches.values()]
        try:
            r = compose(t, None, matches, cvs, prj, llm, records=records)
            verdict = "no-bid" if isinstance(r, NoBid) else "?"
        except Called:
            verdict = "bid"
        except InputError as e:
            verdict = f"input error: {e}"
        verdicts.append({"tender": t["id"], "kind": kind, "verdict": verdict, "best": max(sc), "rows": sc})
        scores.append((kind, sc))
    out["tenders"] = verdicts
    out["tender_bands"] = {kind: dict(collections.Counter(band(s) for k, sc in scores if k == kind for s in sc))
                           for kind in ("simulated", "held-out")}
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("written", out_path)


if __name__ == "__main__":
    main(Path(sys.argv[2]))
