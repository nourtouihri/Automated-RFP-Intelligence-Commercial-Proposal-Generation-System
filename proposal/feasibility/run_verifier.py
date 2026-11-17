"""Agent E audited: the grounding verifier run over the recorded decks.

    python -X utf8 proposal/feasibility/run_verifier.py <out_dir> [--only tender-001 ...]
        [--recordings DIR] [--record] [--force]

The writer replies are replayed exactly as recorded (no writer key needed); the
judge only needs PROPOSAL_VERIFIER_LLM_MODEL (its URL and key fall back to the
writer's, so usually only the model id is new). Each recording runs twice:

  as recorded   the false-positive measure: every partial/unsupported verdict
                on the real decks is a claim for a person to check, all counted
  injected      the recall measure: one claim no source supports ("It was
                delivered in two weeks.") is appended to one prose field in
                each injection-capable step's recorded reply; the verifier
                should rule unsupported for exactly those fields. Evidence
                lines are not injected: their 55-character cap leaves too
                little room for a whole sentence.

For each verdict the run file keeps the step, field, verdict and the judge's
reason; the summary aggregates calls, latency and tokens like run_llm does.
--record writes the judged run's raw replies back into the recordings (a
"verifier" list and source.verifier_model) so proposal.demo replays the same
judgments with no key. Re-running make_recordings.py overwrites that, so
record after regenerating recordings.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from proposal import demo  # noqa: E402
from proposal.compose import InputError, StepError, Trace, compose  # noqa: E402
from proposal.llm_adapter import verifier_call  # noqa: E402
from proposal.schemas import NoBid  # noqa: E402
from proposal.verifier import Verifier  # noqa: E402

MARKER = " It was delivered in two weeks."
INJECT = {  # recorded step -> the first field the marker lands in
    "brief": "key_messages[0]",
    "letter": "paragraphs[0]",
    "summary": "pillars[0].body",
    "needs": "needs[0].body",
    "approach": "phases[0].body",
}


def _injected_replies(recording: dict) -> tuple[list[dict], list[tuple[str, str]]]:
    """The writer replies with one unsourced claim appended, and the (step,
    field) pairs where it landed. A reply that fails to parse is untouched."""
    markers, replies = [], []
    for entry in recording["replies"]:
        reply = {"step": entry["step"], "reply": entry["reply"]}
        try:
            dump = json.loads(entry["reply"])
        except ValueError:
            replies.append(reply)
            continue
        if isinstance(dump, dict) and _append_marker(entry["step"], dump):
            reply["reply"] = json.dumps(dump)
            markers.append((entry["step"], INJECT[entry["step"]]))
        replies.append(reply)
    return replies, markers


def _append_marker(step: str, dump: dict) -> bool:
    items = dump.get({"brief": "key_messages", "letter": "paragraphs",
                      "summary": "pillars", "needs": "needs",
                      "approach": "phases"}[step])
    if not items:
        return False
    first = items[0]
    node = first["body"] if step in ("summary", "needs", "approach") else first
    if not isinstance(node, str) or not node.strip():
        return False
    if isinstance(first, dict):
        first["body"] = node + MARKER
    else:
        items[0] = node + MARKER
    return True


def _same_run(recording: dict, replies: list[dict], judge: Verifier) -> dict:
    """compose() over the given replies, judged; rows with what the judge said."""
    trace = Trace()
    started = time.perf_counter()
    try:
        deck = compose(recording["tender"], None, recording["requirement_matches"],
                       recording["cv_matches"], recording["project_matches"],
                       demo.replay_llm(replies), records=recording["records"],
                       trace=trace, verifier=judge)
    except (demo.ReplayExhausted, InputError, StepError) as e:
        return {"error": f"{type(e).__name__}: {e}", "wall_s": round(time.perf_counter() - started, 1)}
    rows = [(s["step"], row) for s in trace.steps
            for row in (s.get("verifier") if isinstance(s.get("verifier"), list) else [])]
    counts = {v: sum(1 for _, r in rows if r["verdict"] == v)
              for v in ("supported", "partial", "unsupported")}
    return {"kind": "no_bid" if isinstance(deck, NoBid) else "proposal",
            "verdicts": counts, "rows": [{"step": s, **r} for s, r in rows]}


def _catch(results: dict, markers: list[tuple[str, str]]) -> dict:
    """For the injected run: the marker fields that got each verdict."""
    hit = {}
    for step, field in markers:
        row = next((r for r in results["rows"] if r["step"] == step and r["field"] == field), None)
        hit[f"{step}.{field}"] = row["verdict"] if row else "no row"
    return hit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_verifier")
    ap.add_argument("out", type=Path)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--recordings", type=Path, default=demo.RECORDINGS)
    ap.add_argument("--record", action="store_true",
                    help="write the judged replies back into the recordings (for the demo replay)")
    ap.add_argument("--force", action="store_true", help="overwrite existing run files")
    a = ap.parse_args(argv)
    (a.out / "runs").mkdir(parents=True, exist_ok=True)

    model, judge_adapter = verifier_call()
    if judge_adapter is None:
        raise SystemExit("set PROPOSAL_VERIFIER_LLM_MODEL (a judge model different from "
                         "LLM_MODEL); its URL and key fall back to the writer's")
    runs, calls = [], []
    for path in sorted(a.recordings.glob("*.json")):
        if a.only and path.stem not in a.only:
            continue
        run_path = a.out / "runs" / f"{path.stem}.json"
        if run_path.exists() and not a.force:
            runs.append(json.loads(run_path.read_text(encoding="utf-8")))
            continue
        recording = json.loads(path.read_text(encoding="utf-8"))
        injected, markers = _injected_replies(recording)
        results, recorded_entries = {}, None
        for kind, replies in (("recorded", recording["replies"]),
                              ("injected", injected)):
            verifier = Verifier(judge=judge_adapter, model=model)
            run = _same_run(recording, replies, verifier)
            calls += [c for c in verifier.calls if "reply" in c]
            if kind == "recorded" and a.record:
                recorded_entries = [{"step": c["step"], "reply": c["reply"]}
                                    for c in verifier.calls if "reply" in c]
            run["unsourced"] = (_catch(run, markers) if kind == "injected" and "rows" in run
                                else {})
            results[kind] = run
        runs.append({"tender": path.stem, "judge": model, "results": results})
        run_path.write_text(json.dumps(runs[-1], indent=1, ensure_ascii=False),
                            encoding="utf-8")
        injected_run, recorded = results["injected"], results["recorded"]
        print(f"{path.stem}: replay {'ok' if 'error' not in recorded else recorded['error']}; "
              f"recorded supported/partial/unsupported "
              f"{recorded.get('verdicts', {}).get('supported', 0)}/"
              f"{recorded.get('verdicts', {}).get('partial', 0)}/"
              f"{recorded.get('verdicts', {}).get('unsupported', 0)}; "
              f"unsourced claim ruled "
              f"{', '.join(f'{v} ({r})' for r, v in injected_run.get('unsourced', {}).items()) or 'nothing'}",
              flush=True)
        if a.record and recorded_entries is not None:
            out = {**recording, "verifier": recorded_entries}
            out["source"] = {**recording.get("source", {}), "verifier_model": model}
            (a.recordings / path.name).write_text(
                json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  recorded judge replies into {path.name}")
    lat = [c["latency_s"] for c in calls if "latency_s" in c]
    summary = {
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "judge": model,
        "writer_model": sorted({(json.loads(p.read_text(encoding="utf-8")).get("source") or {})
                                .get("model") for p in sorted(a.recordings.glob("*.json"))}
                               - {None}),
        "provider_host": urllib.parse.urlparse(os.environ.get("LLM_URL", "")).hostname,
        "judge_calls": len(calls),
        "latency_p50_s": round(statistics.median(lat), 2) if lat else None,
        "latency_max_s": max(lat) if lat else None,
        "prompt_tokens": sum((c.get("usage") or {}).get("prompt_tokens") or 0 for c in calls),
        "completion_tokens": sum((c.get("usage") or {}).get("completion_tokens") or 0
                                 for c in calls),
        "runs": runs}
    (a.out / "verifier_check.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("judge", "judge_calls", "prompt_tokens",
                                              "completion_tokens", "latency_p50_s")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
