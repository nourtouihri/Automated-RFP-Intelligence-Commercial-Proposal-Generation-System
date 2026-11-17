"""The two-minute demo.

    python -m proposal.demo [tender-001 heldout-001 tender-014] [--replay | --live] [--out out]

Without LLM_API_KEY (or with --replay) it replays a recorded gpt-oss-20b run: the
tender, its RAG hits and source records, and the model's replies are read from
proposal/showcase/recordings/, and the current compose(), render, validator and
exports run on them. No key and no network are needed. With a key (from the
environment or the repo's .env) it calls the model live on the same recorded
inputs; retrieval is not re-run. Each tender writes <id>.pptx, <id>.matrix.csv and,
if LibreOffice is found, <id>.pdf to --out, and prints its bid warnings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import export, render
from .build import DeckRejected, build
from .compose import TASKS, InputError, StepError, Trace, compose, record_id
from .config import DEFAULT
from .llm_adapter import same_model_note, verifier_call
from .measure import FontNotFound, font_gaps
from .schemas import NoBid, Proposal
from .verifier import Verifier

HERE = Path(__file__).resolve().parent
RECORDINGS = HERE / "showcase" / "recordings"
SHOWCASE = ("tender-001", "heldout-001", "tender-014")
MODEL = "openai/gpt-oss-20b"


class ReplayExhausted(RuntimeError):
    pass


def load(tender_id: str) -> dict:
    path = RECORDINGS / f"{tender_id}.json"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in RECORDINGS.glob("*.json")))
        raise SystemExit(f"no recording for {tender_id}; recorded: {known}")
    return json.loads(path.read_text(encoding="utf-8"))


def replay_llm(replies: list[dict]):
    """The recorded replies, served per step in the order the run received them."""
    queues: dict[str, list[str]] = {}
    for r in replies:
        queues.setdefault(r["step"], []).append(r["reply"])

    def llm(system: str, user: str) -> str:
        step = next(k for k in TASKS if system.endswith(TASKS[k]))
        if not queues.get(step):
            raise ReplayExhausted(f"the recording has no more replies for step '{step}'")
        return queues[step].pop(0)
    return llm


def _replay_verifier(rec: dict) -> tuple[Verifier | None, str | None]:
    """(judge, note): the judge replayed from the recording's own entries
    ("verifier" holds its recorded replies, keyed by step like the writers'),
    or (None, None) when the recording has none - an old recording replays
    with the grounding check off."""
    queues: dict[str, list[str]] = {}
    for r in rec.get("verifier") or []:
        queues.setdefault(r["step"], []).append(r["reply"])
    if not queues:
        return None, None

    def judge(system: str, user: str) -> str:
        step = json.loads(user)["STEP"]
        if not queues.get(step):
            raise ReplayExhausted(f"the recording has no more verifier replies for step '{step}'")
        return queues[step].pop(0)

    source = rec.get("source") or {}
    model = source.get("verifier_model", "")
    note = None
    if model and source.get("model", "").lower() == model.lower():
        note = (f"the grounding verifier used the writer's model ({model}): "
                "its rulings may share the writer's blind spots")
    return Verifier(judge=judge, model=model), note


def _verifier_for(how: str, rec: dict) -> tuple[Verifier | None, str | None]:
    """The deck's judge (and a note to print), for replay or live. Live needs
    PROPOSAL_VERIFIER_LLM_MODEL; without it the grounding check is off and
    the demo says so instead of quietly falling back to the writer's model."""
    if how != "live":
        return _replay_verifier(rec)
    model, adapter = verifier_call()
    if adapter is None:
        return None, "verifier: off (no PROPOSAL_VERIFIER_LLM_MODEL)"
    return Verifier(judge=adapter, model=model), same_model_note(model)


def compose_recording(rec: dict, llm=None, *, force_bid: bool = False,
                      verifier=None) -> tuple[Proposal | NoBid, Trace]:
    trace = Trace()
    deck = compose(rec["tender"], None, rec["requirement_matches"], rec["cv_matches"],
                   rec["project_matches"], llm or replay_llm(rec["replies"]), records=rec["records"],
                   trace=trace, force_bid=force_bid, verifier=verifier)
    return deck, trace


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(HERE.parent / ".env")


def mode(*, live: bool, replay: bool) -> str:
    has_key = bool(os.environ.get("LLM_API_KEY"))
    if live and not has_key:
        raise SystemExit("--live needs LLM_API_KEY (and LLM_URL) in the environment or .env")
    return "live" if (live or (has_key and not replay)) else "replay"


def _live_llm(model: str):
    from .llm_adapter import Adapter, openai_call
    os.environ["LLM_MODEL"] = model
    return Adapter(call=openai_call(2048, "low"))


def run_one(tid: str, out: Path, how: str, model: str) -> bool:
    rec = load(tid)
    llm = _live_llm(model) if how == "live" else None
    verifier, note = _verifier_for(how, rec)
    try:
        deck, trace = compose_recording(rec, llm, verifier=verifier)
    except (StepError, InputError, ReplayExhausted) as e:
        print(f"{tid}: failed: {type(e).__name__}: {e}")
        return False
    given = {record_id(h) for hs in [*rec["requirement_matches"].values(), rec["cv_matches"],
                                     rec["project_matches"]] for h in hs}
    try:
        built = build(deck, out / f"{tid}.pptx", retrieved=given, trace=trace, config=DEFAULT)
    except DeckRejected as e:
        print(f"{tid}: no deck written: {e}")
        return False
    files = [built.path, built.csv]
    try:
        files.append(export.to_pdf(built.path))
        pdf = ""
    except (FileNotFoundError, OSError, RuntimeError) as e:
        pdf = f"  PDF skipped: {e}"
    kind = "no-bid deck" if isinstance(deck, NoBid) else "proposal"
    fits = ", ".join(f"{r.fit} {r.score:.2f}" for r in deck.requirements)
    print(f"\n{tid}: {kind}. {rec['tender']['title']} ({rec['tender']['issuer']})")
    if verifier is not None and verifier.model:
        print(f"  grounding verifier: {verifier.model}")
    if note:
        print(f"  note: {note}")
    elif verifier is None and kind == "proposal":
        print("  note: grounding verifier off (the recording has no grounding verdicts)")
    print(f"  matrix: {fits}")
    print("  wrote " + ", ".join(str(f) for f in files) + (f"\n{pdf}" if pdf else ""))
    for w in built.warnings:
        print(f"  warning: {w}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m proposal.demo")
    ap.add_argument("tenders", nargs="*", default=list(SHOWCASE))
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--replay", action="store_true", help="replay the recorded replies (no key)")
    group.add_argument("--live", action="store_true", help="call the model (needs LLM_API_KEY)")
    ap.add_argument("--out", default="out")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args(argv)
    _load_dotenv()
    how = mode(live=a.live, replay=a.replay)
    for tid in a.tenders:
        load(tid)
    render.apply_theme("website")
    try:  # the template's own files, checked once, before any deck is written
        render.check_logos(DEFAULT)
        font_gaps((render.FONT, render.HEAD_FONT))
    except (render.LogoError, FontNotFound) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = Path(a.out)
    where = (f"live, {a.model}, on the recorded RAG hits" if how == "live" else
             "replay of a recorded gpt-oss-20b run: no API key, no network")
    print(f"proposal demo: {where}. Output: {out.resolve()}")
    ok = [run_one(tid, out, how, a.model) for tid in a.tenders]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
