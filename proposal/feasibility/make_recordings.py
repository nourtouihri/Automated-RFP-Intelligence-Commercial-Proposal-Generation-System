"""Turn recorded run_llm.py runs into self-contained recordings for proposal.demo.

    python -X utf8 proposal/feasibility/make_recordings.py <runs_dir> <tender-id> ... [--feed <dir>]

A run file holds the model's replies but not the retrieval hits. This re-runs the
same in-memory retrieval run_llm.py used (deterministic: same corpus, same model),
keeps only the source records those hits name, and writes
proposal/showcase/recordings/<tender-id>.json. It replays each recording through
the current compose() and stops if the deck differs from the one the run recorded
(aside from the date, the research warning and the buyer slide's research flag, since
the run passed research=None, the dropped footprint row, and the no-bid
recommendation, which code writes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_llm as R  # noqa: E402  (loads .env and puts the repo on sys.path)
from proposal import compose as C  # noqa: E402
from proposal.demo import RECORDINGS, compose_recording  # noqa: E402


def main(argv: list[str]) -> None:
    feed = Path(argv[argv.index("--feed") + 1]) if "--feed" in argv else None
    args = [a for i, a in enumerate(argv) if a != "--feed" and (i == 0 or argv[i - 1] != "--feed")]
    runs_dir, ids = Path(args[0]), args[1:]
    search, _ = R.retriever()
    records = C.load_records(R.REPO / "Cvs dataset")
    by_id = {t["id"]: t for t in R.tenders(feed)}
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    for tid in ids:
        run = json.loads((runs_dir / "runs" / f"{tid}.json").read_text(encoding="utf-8"))
        t = by_id[tid]
        reqs = t["requirements"]
        query = "\n".join([t["title"], t["issuer"], *reqs])
        matches = {r: search(r, top_k=5) for r in reqs}
        cvs, projects = search(query, top_k=3, doc_type="cv"), search(query, top_k=5, doc_type="project")
        hits = [h for hs in [*matches.values(), cvs, projects] for h in hs]
        rec = {"source": {"run": runs_dir.name, "model": run["model"], "kind": run["kind"],
                          "note": "replies recorded from a real run; hits re-retrieved with the same "
                                  "in-memory RAG (run_llm.py)"},
               "tender": t, "requirement_matches": matches, "cv_matches": cvs,
               "project_matches": projects,
               "records": {C.record_id(h): records[C.record_id(h)] for h in hits
                           if C.record_id(h) in records},
               "replies": [{"step": c["step"], "reply": c["reply"]} for c in run["calls"]]}
        deck, _ = compose_recording(rec, force_bid=run["kind"] == "proposal")
        got, want = deck.model_dump(), dict(run["deck"])
        for d in (got, want):
            d["meta"] = {**d["meta"], "date": None}
            d.pop("input_warnings", None)
            d.pop("recommendation", None)
            if "buyer" in d:
                d["buyer"] = {k: v for k, v in d["buyer"].items() if k != "researched"}
                d["buyer"]["profile"] = {k: v for k, v in d["buyer"]["profile"].items()
                                         if k != "footprint"}  # the row was dropped
            if "warnings" in d:
                d["warnings"] = [w for w in d["warnings"] if not w.startswith("research unavailable")]
        assert got == want, f"replay of {tid} differs from the recorded deck"
        path = RECORDINGS / f"{tid}.json"
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{path} ({len(rec['replies'])} replies, {len(rec['records'])} records): replay matches")


if __name__ == "__main__":
    main(sys.argv[1:])
