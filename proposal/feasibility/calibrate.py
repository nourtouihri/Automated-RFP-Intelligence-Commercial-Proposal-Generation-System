"""Where do real matches score? Uses the repo's own labelled queries.

    python -I proposal/feasibility/calibrate.py <repo_root> <minilm_onnx_dir>

rag/eval_dataset.json lists 13 queries with the record that should be found.
For each, print the similarity of that right record and of the best wrong
record of the same type, as rag/query.py would rank them.

On this snapshot the 8 cv/project labels rank 22nd or lower (None = not in
the top 50): they point at records whose content no longer matches the query,
e.g. CV-0007 is a BigQuery data engineer, not a FastAPI backend engineer. The
dataset was regenerated after the labels were written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_feasibility import MiniLM, load_corpus, record_id, search  # noqa: E402


def main(repo: Path, model_dir: Path):
    model = MiniLM(model_dir)
    chunks, _ = load_corpus(repo)
    cvecs = model.embed([c["content"] for c in chunks])
    cases = json.loads((repo / "rag" / "eval_dataset.json").read_text(encoding="utf-8"))
    out = []
    for case in cases:
        hits = search(model.embed([case["query"]])[0], chunks, cvecs, case["doc_type"], top_k=50)
        right = [h for h in hits if record_id(h) in case["relevant_ids"]]
        wrong = [h for h in hits if record_id(h) not in case["relevant_ids"]]
        out.append({"case": case["id"], "rank_of_right": hits.index(right[0]) + 1 if right else None,
                    "right": round(right[0]["similarity"], 3) if right else None,
                    "best_wrong": round(wrong[0]["similarity"], 3)})
    for r in out:
        print(f"{r['case']:32} rank {r['rank_of_right']}  right {r['right']}  best wrong {r['best_wrong']}")
    print(json.dumps(out))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
