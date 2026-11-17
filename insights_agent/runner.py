"""The agent loop: the LLM chooses, the code checks, runs and records.

The LLM picks actions from a fixed list. It never produces a number, a
confidence level or a URL. Every turn goes into a trace that can be shown in
the demo ("here is what the agent did and why").
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from insights_agent.agent_prompts import AGENT_SYSTEM, RESULT_CAP_CHARS, build_turn_message
from insights_agent.extractor import _strip_fences
from insights_agent.positioning import build_positioning
from insights_agent.schemas import COMPETITOR_CATEGORIES, BudgetEstimate, Competitor, TenderInsights
from insights_agent.tools import ALLOWED_ACTIONS, AgentContext, run_tool

logger = logging.getLogger(__name__)

MAX_TURNS = 10
TIME_LIMIT_S = 120.0
LLM_TIMEOUT_S = 60.0
LLM_RETRY_PAUSE_S = 4.0  # pause before the first retry; the second retry waits 5x longer
LLM_RETRIES = 2          # retries after an LLM service failure (429, timeout...)
MAX_INVALID = 2          # consecutive unusable turns before the agent gives up
MAX_COMPETITORS = 5
THOUGHT_CAP = 300
PREVIEW_CAP = 600
ARGS_CAP = 300           # args shown to the LLM in the history (keeps the prompt short)
TRACE_ARGS_CAP = 1500    # args kept in the trace (a workload must stay readable in the demo)


@dataclass
class AgentRun:
    insights: TenderInsights
    trace: list[dict] = field(default_factory=list)
    # finished | max_turns | time_limit | invalid_output | llm_error
    stop_reason: str = "max_turns"
    ctx: Optional[AgentContext] = None


def _dump(value: Any, cap: int) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:cap]


def _llm_error_detail(exc: BaseException) -> str:
    """Short, key-free description of an LLM failure for the trace (type + HTTP status)."""
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    detail = type(exc).__name__
    if status:
        detail += f":{status}"
    return detail


def compute_confidence(budget: BudgetEstimate, finished_cleanly: bool) -> str:
    """Confidence comes from the evidence, never from the model."""
    if budget.method == "none":
        return "low"
    if not finished_cleanly and budget.confidence == "high":
        return "medium"
    return budget.confidence


def build_competitors(ctx: AgentContext) -> list[Competitor]:
    """Group verified facts by company. Strengths and weaknesses exist only if a page says so."""
    grouped: dict[str, dict] = {}
    for fact in ctx.web_facts:
        if fact.category not in COMPETITOR_CATEGORIES or not fact.name:
            continue
        e = grouped.setdefault(
            fact.name.casefold(),
            {"name": fact.name, "why": None, "first": fact.value[:500],
             "strengths": [], "weaknesses": [], "urls": []},
        )
        text = fact.value[:300]
        if fact.category == "competitor" and e["why"] is None:
            e["why"] = fact.value[:500]
        elif fact.category == "competitor_strength" and text not in e["strengths"]:
            e["strengths"].append(text)
        elif fact.category == "competitor_weakness" and text not in e["weaknesses"]:
            e["weaknesses"].append(text)
        if fact.source_url not in e["urls"]:
            e["urls"].append(fact.source_url)
    return [
        Competitor(
            name=e["name"][:200], why_likely=e["why"] or e["first"],
            strengths=e["strengths"][:3], weaknesses=e["weaknesses"][:3], evidence=e["urls"],
        )
        for e in list(grouped.values())[:MAX_COMPETITORS]
    ]


def _status(finished: bool, budget: BudgetEstimate, valid_actions: int) -> str:
    if valid_actions == 0:
        return "unavailable"
    if finished and budget.method != "none":
        return "complete"
    return "partial"


async def _ask_llm(
    llm_call, message: str, remaining: float, start: float, time_limit_s: float
) -> tuple[str, int]:
    """One LLM call, with up to LLM_RETRIES retries if the service itself fails (429, timeout...).

    Pauses grow (LLM_RETRY_PAUSE_S, then 5x), which gives a rate limit time to reset.
    Returns (raw answer, number of attempts). A malformed answer is NOT retried
    here: that is handled by the invalid-turn counter in the loop.
    """
    attempt = 0
    while True:
        attempt += 1
        left = time_limit_s - (time.monotonic() - start)
        timeout = max(0.1, min(left, LLM_TIMEOUT_S))
        try:
            raw = await asyncio.wait_for(llm_call(message, system=AGENT_SYSTEM), timeout=timeout)
            return raw, attempt
        except Exception:
            if attempt > LLM_RETRIES:
                raise
            pause = LLM_RETRY_PAUSE_S * (5 ** (attempt - 1))
            left = time_limit_s - (time.monotonic() - start)
            if left <= pause + 1.0:
                raise  # not enough time left for a retry
            logger.warning("LLM call failed (attempt %d), retrying in %.0fs", attempt, pause,
                           exc_info=True)
            await asyncio.sleep(pause)


async def run_agent(
    tender: dict,
    *,
    llm_call=None,
    web_search=None,
    fetch_page=None,
    rag_query=None,
    daily_rate: Optional[float] = None,
    max_turns: int = MAX_TURNS,
    time_limit_s: float = TIME_LIMIT_S,
) -> AgentRun:
    if llm_call is None:
        from insights_agent.llm import default_llm_call  # lazy: easy to fake in tests
        llm_call = default_llm_call

    ctx = AgentContext(
        tender=tender, llm_call=llm_call, web_search=web_search,
        fetch_page=fetch_page, rag_query=rag_query, daily_rate=daily_rate,
    )
    start = time.monotonic()
    trace: list[dict] = []
    history: list[str] = []
    invalid_in_a_row = 0
    valid_actions = 0
    finished = False
    stop_reason = "max_turns"

    for turn in range(1, max_turns + 1):
        remaining = time_limit_s - (time.monotonic() - start)
        if remaining <= 0:
            stop_reason = "time_limit"
            break

        t0 = time.monotonic()
        step: dict = {
            "turn": turn, "action": None, "args": {}, "thought": "",
            "ok": False, "error": None, "result_preview": "", "seconds": 0.0,
        }

        data: Optional[dict] = None
        try:
            raw, attempts = await _ask_llm(
                llm_call,
                build_turn_message(ctx.tender_title, history, turn, max_turns),
                remaining, start, time_limit_s,
            )
            if attempts > 1:
                step["llm_retried"] = True
        except Exception as exc:
            logger.warning("agent turn %d: LLM call failed", turn, exc_info=True)
            step["error"] = "llm_call_failed"
            step["llm_error_detail"] = _llm_error_detail(exc)
        else:
            try:
                cleaned = _strip_fences((raw or "").strip())
                parsed = json.loads(cleaned) if cleaned else None
                data = parsed if isinstance(parsed, dict) else None
                if data is None:
                    step["error"] = "invalid_json"
            except json.JSONDecodeError:
                step["error"] = "invalid_json"

        action = data.get("action") if data else None
        if data is not None and (not isinstance(action, str) or action not in ALLOWED_ACTIONS):
            step["error"] = "unknown_action"
            step["action"] = action[:50] if isinstance(action, str) else None

        if step["error"]:
            step["seconds"] = round(time.monotonic() - t0, 3)
            trace.append(step)
            if step["error"] == "llm_call_failed":
                history.append(
                    f"Turn {turn}: no answer received (technical error). "
                    "Answer with one valid JSON action."
                )
            else:
                history.append(
                    f"Turn {turn}: INVALID ({step['error']}). Answer with one valid JSON action."
                )
            invalid_in_a_row += 1
            if invalid_in_a_row >= MAX_INVALID:
                stop_reason = "llm_error" if step["error"] == "llm_call_failed" else "invalid_output"
                break
            continue

        invalid_in_a_row = 0
        valid_actions += 1
        thought = data.get("thought")
        step["thought"] = thought[:THOUGHT_CAP] if isinstance(thought, str) else ""
        step["action"] = action
        args = {k: v for k, v in data.items() if k not in ("action", "thought")}
        # Some models nest the arguments: {"action": ..., "arguments": {...}}.
        if set(args) == {"arguments"} and isinstance(args["arguments"], dict):
            args = args["arguments"]
        args_json = _dump(args, 10_000)
        if len(args_json) <= TRACE_ARGS_CAP:
            step["args"] = json.loads(args_json)
        else:
            step["args"] = {"truncated": True, "preview": args_json[:TRACE_ARGS_CAP]}

        if action == "finish":
            step.update(ok=True, result_preview="finished", seconds=round(time.monotonic() - t0, 3))
            trace.append(step)
            finished = True
            stop_reason = "finished"
            break

        # A slow tool must not push the run past the time limit.
        try:
            result = await asyncio.wait_for(
                run_tool(action, args, ctx),
                timeout=max(0.1, time_limit_s - (time.monotonic() - start)),
            )
        except asyncio.TimeoutError:
            result = {"ok": False, "error": "tool_timeout"}
        step["ok"] = bool(result.get("ok"))
        step["error"] = None if step["ok"] else result.get("error")
        step["result_preview"] = _dump(result, PREVIEW_CAP)
        step["seconds"] = round(time.monotonic() - t0, 3)
        trace.append(step)
        history.append(f"Turn {turn}: {action} {_dump(args, ARGS_CAP)} -> {_dump(result, RESULT_CAP_CHARS)}")

    # The agent may stop, forget or run out of turns: the code still resolves the budget.
    if ctx.budget is None:
        t0 = time.monotonic()
        result = await run_tool("compute_budget", {}, ctx)
        trace.append({
            "turn": None, "action": "compute_budget", "args": {}, "thought": "",
            "auto": True, "ok": bool(result.get("ok")), "error": result.get("error"),
            "result_preview": _dump(result, PREVIEW_CAP),
            "seconds": round(time.monotonic() - t0, 3),
        })
    budget = ctx.budget or BudgetEstimate(
        method="none", confidence="low",
        assumptions=["The budget could not be computed."],
    )

    insights = TenderInsights(
        tender_id=ctx.tender_id,
        issuer=str(tender.get("issuer") or "unknown"),
        budget=budget,
        competitors=build_competitors(ctx),
        positioning=build_positioning(ctx),
        notes=f"stop_reason={stop_reason}; turns={sum(1 for s in trace if not s.get('auto'))}",
        confidence=compute_confidence(budget, finished),
        status=_status(finished, budget, valid_actions),
        completed_at=datetime.now(timezone.utc),
    )
    return AgentRun(insights=insights, trace=trace, stop_reason=stop_reason, ctx=ctx)