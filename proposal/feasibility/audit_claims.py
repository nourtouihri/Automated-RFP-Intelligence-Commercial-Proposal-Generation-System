"""Replay recorded LLM replies through compose() offline (no API calls) and list
every claim the hallucination check flags, plus a seeded sample of unflagged
fields, for a human to judge.

    python -X utf8 proposal/feasibility/audit_claims.py <runs_dir>:<feed_dir> ... --out audit_claims.json

<runs_dir> holds the runs/*.json written by run_llm.py; <feed_dir> the tender JSON
files it read (default: detection/data/simulated_feed; held-out: proposal/feasibility/heldout).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_llm as R  # noqa: E402  (loads .env and the repo on sys.path)
from proposal import compose as C  # noqa: E402
from proposal.claims import extract, support_text, unsupported  # noqa: E402


def replay(tender: dict, rec: dict, search, records: dict):
    calls = iter(rec["calls"])

    def llm(system, user):
        c = next(calls)
        assert system.endswith(C.TASKS[c["step"]]), (tender["id"], c["step"])
        return c["reply"]

    reqs = tender["requirements"]
    matches = {r: search(r, top_k=5) for r in reqs}
    query = "\n".join([tender["title"], tender["issuer"], *reqs])
    cvs, projects = search(query, top_k=3, doc_type="cv"), search(query, top_k=5, doc_type="project")
    seen, trace = [], C.Trace()
    original = C.run_step

    def capture(name, schema, payload, *a, **kw):
        out = original(name, schema, payload, *a, **kw)
        seen.append((name, out.model_dump(), payload))
        return out

    C.run_step = capture
    try:
        deck = C.compose(tender, None, matches, cvs, projects, llm, records=records, trace=trace,
                        claim_check=True, force_bid=rec.get("kind") == "proposal")
    except C.StepError:
        deck = None
    finally:
        C.run_step = original
    wide = "\n".join([tender["title"], tender["issuer"], tender.get("raw_text", ""), *reqs]
                     + [h["content"] for hs in [*matches.values(), cvs, projects] for h in hs]
                     + [json.dumps(records[C.record_id(h)], ensure_ascii=False)
                        for hs in [*matches.values(), cvs, projects] for h in hs if C.record_id(h) in records])
    return deck, trace, seen, wide


def main(argv: list[str]) -> None:
    out_path = Path(argv[argv.index("--out") + 1])
    pairs = [a for a in argv[1:] if ":" in a and not a.startswith("--")]
    search, _ = R.retriever()
    records = C.load_records(R.REPO / "Cvs dataset")
    flagged, unflagged, summary = [], [], []
    for pair in pairs:
        runs_dir, feed = (Path(x) for x in pair.split(":"))
        by_id = {t["id"]: t for t in R.tenders(feed)}
        for path in sorted((runs_dir / "runs").glob("*.json")):
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec["tender"] not in by_id:
                continue
            deck, trace, seen, wide = replay(by_id[rec["tender"]], rec, search, records)
            if deck is not None and rec["ok"]:
                assert deck.model_dump() == rec["deck"], f"replay differs for {rec['tender']}"
            summary.append({"run": runs_dir.name, "tender": rec["tender"], "ok": deck is not None,
                            "steps": len(trace.steps)})
            for entry, (name, output, payload) in zip(trace.steps, seen):  # a step can repeat (evidence)
                support = support_text(C.DEFAULT.company_sentence, C.TASKS[name], payload, records)
                step_flags = {(u["field"], u["claim"]) for u in entry.get("unsupported", [])}
                for u in entry.get("unsupported", []):
                    elsewhere = not unsupported({"f": "see " + u["claim"]}, wide)
                    flagged.append({"run": runs_dir.name, "tender": rec["tender"], "step": name, **u,
                                    "in_wider_tender_context": elsewhere})
                for field, text in C._strings(output):
                    if ".evidence[" in field or not text.strip():
                        continue
                    if not any(f == field for f, _ in step_flags):
                        unflagged.append({"run": runs_dir.name, "tender": rec["tender"], "step": name,
                                          "field": field, "text": text,
                                          "checked": [c["claim"] for c in extract(text)]})
    sample = random.Random(7).sample(unflagged, min(40, len(unflagged)))
    out_path.write_text(json.dumps({"tenders": summary, "flagged": flagged, "unflagged_total": len(unflagged),
                                    "unflagged_sample": sample}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"tenders {len(summary)}, decks {sum(s['ok'] for s in summary)}, flags {len(flagged)}, "
          f"fields with no flag {len(unflagged)}")


if __name__ == "__main__":
    main(sys.argv)
