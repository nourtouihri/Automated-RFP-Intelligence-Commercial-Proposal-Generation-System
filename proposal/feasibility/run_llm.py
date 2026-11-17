"""First real-LLM run: compose() on every simulated tender that has requirements.

    python -X utf8 proposal/feasibility/run_llm.py <out_dir> [--only tender-012 ...] [--feed <dir>]
        [--reasoning-effort low] [--max-completion-tokens 2048] [--fallback-model openai/gpt-oss-20b]
        [--claim-check] [--force-bid] [--allow-issues] [--force]

- LLM: proposal.llm_adapter over the repo's .env. Without --reasoning-effort or
  --max-completion-tokens it calls detection/llm.py's llm_call (the production
  path, capped at 1024 tokens); with either, the adapter's own request, which
  sends max_completion_tokens (default 2048) and also returns token usage.
  --fallback-model takes over for the remaining tenders once the provider's
  daily quota stops the first model.
- Retrieval: the repo's in-memory RAG (rag/evaluate_local.py: production
  chunkers, rag.embeddings, rag.ranking boost) on main's corpus. Per tender,
  5 hits per requirement, then n8n's tender query (title, issuer and
  requirements, one per line) for 3 CVs and 5 projects. Facts come from
  compose.load_records("Cvs dataset"). Research is not run: research=None.
- compose() returns a proposal, or a no-bid result when every requirement is a Gap
  (no model call; --force-bid writes the proposal anyway). The deck goes through
  build(): rendered, validated, written only if the validator passes (--allow-issues
  writes it anyway), then converted to PDF. --claim-check turns the claim check on.
  One JSON per tender is written as soon as it finishes, so a stopped run resumes
  where it stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")
# .env.example ships EMBEDDING_MODEL empty, and rag.embeddings would pass ""
# to SentenceTransformer as the model name (Docker substitutes the default).
os.environ["EMBEDDING_MODEL"] = (os.environ.get("EMBEDDING_MODEL")
                                 or "sentence-transformers/all-MiniLM-L6-v2")

from proposal import render  # noqa: E402
from proposal.build import DeckRejected, build  # noqa: E402
from proposal.compose import (InputError, StepError, Trace, bid_warnings, compose,  # noqa: E402
                              llm_texts, load_records, record_id)
from proposal.export import to_pdf  # noqa: E402
from proposal.llm_adapter import Adapter, QuotaExhausted, openai_call  # noqa: E402
from proposal.schemas import NoBid  # noqa: E402
from rag.embeddings import embed_batch  # noqa: E402
from rag.evaluate_local import LocalRetriever, load_corpus  # noqa: E402

FLAGS = {"number": r"\d", "delivered": r"(?i)\bdeliver", "money/percent": r"[%€$£]"}


def retriever() -> tuple[LocalRetriever, int]:
    d = REPO / "Cvs dataset"
    docs = load_corpus(d / "fake_cvs.json", d / "fake_projects.json", d / "fake_tools.json",
                       d / "olivesoft_projects.json")
    return LocalRetriever(docs, embed_batch([doc["content"] for doc in docs])), len(docs)


def tenders(feed_dir: Path | None = None) -> list[dict]:
    feed = sorted((feed_dir or REPO / "detection" / "data" / "simulated_feed").glob("*.json"))
    return [t for t in (json.loads(f.read_text(encoding="utf-8")) for f in feed)
            if t.get("requirements")]


def run_tender(t: dict, search, records: dict, llm: Adapter, out: Path, *, claim_check: bool,
               force_bid: bool, allow_issues: bool) -> dict:
    reqs = t["requirements"]
    matches = {req: search(req, top_k=5) for req in reqs}
    query = "\n".join([t["title"], t["issuer"], *reqs])  # n8n "Prepare RAG Context"
    cvs = search(query, top_k=3, doc_type="cv")
    projects = search(query, top_k=5, doc_type="project")
    given = {record_id(h) for hits in [*matches.values(), cvs, projects] for h in hits}
    trace, llm.calls = Trace(), []
    result = {"tender": t["id"], "title": t["title"], "model": os.environ["LLM_MODEL"],
              "cv_similarities": [round(c["similarity"], 3) for c in cvs]}
    started = time.perf_counter()
    try:
        deck = compose(t, None, matches, cvs, projects, llm, records=records, trace=trace,
                       claim_check=claim_check, force_bid=force_bid)
    except (StepError, InputError) as e:
        result.update(kind="failed", ok=False, error=f"{type(e).__name__}: {e}")
    else:
        result.update(kind="no_bid" if isinstance(deck, NoBid) else "proposal", deck=deck.model_dump())
        try:
            built = build(deck, out / "decks" / f"{t['id']}.pptx", retrieved=given,
                          allow_issues=allow_issues, trace=trace)
        except DeckRejected as e:
            result.update(ok=False, error=f"DeckRejected: {e}", issues=[str(i) for i in e.issues],
                          bid_warnings=bid_warnings(deck, trace))
        else:
            flags = [] if isinstance(deck, NoBid) else [
                (where, kind, text) for where, text in llm_texts(deck)
                for kind, rx in FLAGS.items() if re.search(rx, text)]
            result.update(ok=True, issues=[str(i) for i in built.issues],
                          bid_warnings=built.warnings, flags=flags)
            to_pdf(built.path)
    result.update(wall_s=round(time.perf_counter() - started, 1), steps=trace.steps,
                  calls=llm.calls)
    return result


def tokens(call: dict, key: str) -> int:
    usage = call.get("usage") or {}
    if key == "reasoning_tokens":
        return (usage.get("completion_tokens_details") or {}).get(key) or 0
    return usage.get(key) or 0


def summarize(out: Path, chunks: int, transport: str) -> dict:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "runs").glob("*.json"))]
    per_step: dict[str, dict] = {}
    for r in runs:
        calls = iter(r["calls"])
        for s in r["steps"]:
            agg = per_step.setdefault(s["step"], {"steps": 0, "attempts": 0, "parse_failures": 0,
                                                  "citation_failures": 0, "failed_steps": 0,
                                                  "latency_s": [], "rate_limited": 0,
                                                  "waited_s": 0.0, "truncated": 0,
                                                  "prompt_tokens": 0, "completion_tokens": 0,
                                                  "reasoning_tokens": 0, "trimmed": 0})
            agg["steps"] += 1
            agg["attempts"] += s["attempts"]
            agg["failed_steps"] += not s["ok"]
            agg["trimmed"] += len(s.get("trimmed", []))
            for f in s["failures"]:
                agg[f"{f['kind']}_failures"] += 1
            for c in [next(calls) for _ in range(s["attempts"])]:
                agg["latency_s"].append(c["latency_s"])
                agg["rate_limited"] += c["rate_limited"]
                agg["waited_s"] += c["waited_s"]
                agg["truncated"] += c["finish_reason"] == "length"
                for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
                    agg[k] += tokens(c, k)
    for agg in per_step.values():
        lat = agg.pop("latency_s")
        agg.update(latency_p50_s=round(statistics.median(lat), 2), latency_max_s=max(lat),
                   waited_s=round(agg["waited_s"], 1))
    kind = lambda r: r.get("kind") or ("proposal" if r["ok"] else "failed")  # noqa: E731
    per_tender = [{"tender": r["tender"], "model": r["model"], "ok": r["ok"], "kind": kind(r),
                   "error": r.get("error"), "calls": len(r["calls"]),
                   "failures": sum(len(s["failures"]) for s in r["steps"]),
                   "issues": len(r.get("issues", [])), "bid_warnings": r.get("bid_warnings"),
                   "flags": len(r.get("flags", [])),
                   "unsupported": sum(len(s.get("unsupported", [])) for s in r["steps"]),
                   "banned_hits": sum(w.startswith("banned wording") for w in r.get("bid_warnings") or []),
                   "trimmed": [f"{s['step']}.{t['field']} {t['from']}->{t['to']} ({t['how']})"
                               for s in r["steps"] for t in s.get("trimmed", [])],
                   "tokens": sum(tokens(c, k) for c in r["calls"]
                                 for k in ("prompt_tokens", "completion_tokens")),
                   "llm_s": round(sum(c["latency_s"] for c in r["calls"]), 1),
                   "wall_s": r["wall_s"]} for r in runs]
    git = lambda *a: subprocess.run(["git", "-C", str(REPO), *a], capture_output=True,  # noqa: E731
                                    text=True).stdout.strip()
    summary = {
        "provenance": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                       "commit": git("rev-parse", "--short", "HEAD"),
                       "uncommitted_changes": bool(git("status", "--porcelain", "proposal")),
                       "models": sorted({r["model"] for r in runs}),
                       "provider_host": urlparse(os.environ.get("LLM_URL", "")).hostname,
                       "transport": transport, "corpus_chunks": chunks,
                       "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "calls": (n := sum(v["attempts"] for v in per_step.values())),
        "rejected_replies": (bad := sum(v["parse_failures"] + v["citation_failures"]
                                        for v in per_step.values())),
        "rejected_share": round(bad / n, 3) if n else None,
        "decks_ok": sum(r["ok"] and kind(r) == "proposal" for r in runs),
        "no_bid": [r["tender"] for r in runs if kind(r) == "no_bid"],
        "failed": [r["tender"] for r in runs if not r["ok"]],
        "per_step": per_step, "per_tender": per_tender}
    (out / "llm_run.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="run_llm")
    ap.add_argument("out", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--reasoning-effort")
    ap.add_argument("--max-completion-tokens", type=int)
    ap.add_argument("--claim-check", action="store_true", help="run the claim check (off by default)")
    ap.add_argument("--force-bid", action="store_true", help="write the proposal even if every row is a Gap")
    ap.add_argument("--allow-issues", action="store_true", help="write decks the validator rejects")
    ap.add_argument("--fallback-model")
    ap.add_argument("--feed", type=Path, help="folder of tender JSON files (default: detection/data/simulated_feed)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    (a.out / "decks").mkdir(parents=True, exist_ok=True)
    (a.out / "runs").mkdir(exist_ok=True)
    if a.reasoning_effort or a.max_completion_tokens:
        cap = a.max_completion_tokens or 2048
        llm = Adapter(call=openai_call(cap, a.reasoning_effort))
        transport = f"openai_call(max_completion_tokens={cap}, reasoning_effort={a.reasoning_effort})"
    else:
        llm, transport = Adapter(), "detection.llm.llm_call"
    render.apply_theme("website")
    search, chunks = retriever()
    records = load_records(REPO / "Cvs dataset")
    for t in tenders(a.feed):
        path = a.out / "runs" / f"{t['id']}.json"
        if (a.only and t["id"] not in a.only) or (path.exists() and not a.force):
            continue
        try:
            result = run_tender(t, search, records, llm, a.out, claim_check=a.claim_check,
                                force_bid=a.force_bid, allow_issues=a.allow_issues)
        except QuotaExhausted as e:
            if not a.fallback_model or os.environ["LLM_MODEL"] == a.fallback_model:
                print(f"stopped before {t['id']}: {e}")
                break
            print(f"{os.environ['LLM_MODEL']} stopped ({e}); switching to {a.fallback_model}")
            os.environ["LLM_MODEL"] = a.fallback_model
            result = run_tender(t, search, records, llm, a.out, claim_check=a.claim_check,
                                force_bid=a.force_bid, allow_issues=a.allow_issues)
        path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{t['id']}: {result['kind']} ok={result['ok']} calls={len(result['calls'])} "
              f"failures={sum(len(s['failures']) for s in result['steps'])} "
              f"issues={len(result.get('issues', []))} wall={result['wall_s']}s "
              f"{result.get('error', '')}", flush=True)
    print(json.dumps(summarize(a.out, chunks, transport), indent=1)[:4000])


if __name__ == "__main__":
    main()
