"""Run the speed-promise check (compose.speed_promises) on every recorded deck.

    python -X utf8 proposal/feasibility/speed_check.py <out.json> <runs_dir> ...

Each <runs_dir> holds runs/*.json written by run_llm.py. A deck's model-written text
is read from the recorded deck (the same fields compose.llm_texts reads); the tender
text comes from the simulated feed or the held-out set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from proposal.compose import speed_promises, tender_duration  # noqa: E402
from proposal.schemas import PARTIAL_AT  # noqa: E402


def texts(d: dict) -> list[tuple[str, str]]:
    out = [("meta.headline", d["meta"]["headline"]), ("meta.subtitle", d["meta"]["subtitle"]),
           ("letter.salutation", d["letter"]["salutation"])]
    out += [(f"letter.paragraphs[{i}]", t) for i, t in enumerate(d["letter"]["paragraphs"])]
    out += [("letter.closing", d["letter"]["closing"]), ("summary.title", d["summary"]["title"])]
    out += [(f"summary.pillars[{i}].{k}", p[k]) for i, p in enumerate(d["summary"]["pillars"])
            for k in ("title", "body")]
    out += [("summary.why_us", d["summary"]["why_us"])]
    out += [(f"buyer.needs[{i}].{k}", n[k]) for i, n in enumerate(d["buyer"]["needs"])
            for k in ("title", "body")]
    out += [(f"requirements[{i}].evidence", r["evidence"]) for i, r in enumerate(d["requirements"])
            if r.get("evidence_id") and r["score"] >= PARTIAL_AT]
    out += [(f"approach.phases[{i}].{k}", p[k]) for i, p in enumerate(d["approach"]["phases"])
            for k in ("name", "body")]
    return out


def main(argv: list[str]) -> None:
    out_path, run_dirs = Path(argv[0]), [Path(a) for a in argv[1:]]
    feeds = [REPO / "detection" / "data" / "simulated_feed", REPO / "proposal" / "feasibility" / "heldout"]
    tenders = {t["id"]: t for f in feeds for t in
               (json.loads(p.read_text(encoding="utf-8")) for p in sorted(f.glob("*.json")))}
    decks, hits, no_duration = 0, [], []
    for run_dir in run_dirs:
        for path in sorted((run_dir / "runs").glob("*.json")):
            rec = json.loads(path.read_text(encoding="utf-8"))
            deck, tender = rec.get("deck") or {}, tenders.get(rec["tender"])
            if "letter" not in deck or tender is None:
                continue
            decks += 1
            if not tender_duration(tender):
                no_duration.append(f"{run_dir.name}/{rec['tender']}")
            for w in speed_promises(texts(deck), tender):
                hits.append({"run": run_dir.name, "tender": rec["tender"], "warning": w})
    result = {"decks": decks, "decks_whose_tender_states_no_duration": no_duration, "hits": hits}
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{decks} decks, {len(hits)} hits, {len(no_duration)} decks with no stated duration")
    for h in hits:
        print(f"  {h['run']}/{h['tender']}: {h['warning']}")


if __name__ == "__main__":
    main(sys.argv[1:])
