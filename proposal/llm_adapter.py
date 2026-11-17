"""compose()'s llm(system, user) over the repo's LLM settings (.env).

The default call is detection/llm.py's llm_call, the transport production
uses. llm_call fails fast on every 4xx and retries 5xx once, while Groq
rate-limits per minute, so the adapter spaces its calls, waits out HTTP 429
(Retry-After), retries timeouts and 5xx with a backoff, and records each call.
openai_call() is the adapter's own request, for settings llm_call cannot send
(reasoning_effort, max_completion_tokens); it also keeps the usage and
finish_reason that llm_call drops. Errors carry the HTTP status and the
provider's message, never the request headers, which hold the API key.

Every LLM_* setting has a proposal-scoped override (PROPOSAL_LLM_*): when a
PROPOSAL_LLM_* variable is set to a non-empty value it wins, otherwise the
shared .env value is used. That lets the deck run against a different
model/provider without touching detection and research. PER_CALL_TIMEOUT_
PROPOSAL (default 120s) already plays this role for the call timeout; it is
only read in this package, so no shared name gained a proposal meaning.

The grounding verifier (verifier.Verifier) is the one caller with its own
model, by design: PROPOSAL_VERIFIER_LLM_MODEL names it (there is deliberately
no fallback to the writer's model - a same-model check would defeat a
different-model guard). Its URL and key fall back PROPOSAL_VERIFIER_LLM_* ->
PROPOSAL_LLM_* -> shared LLM_*, so the judge usually shares the writer's
provider and key, with just the model id set.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from .compose import TASKS


@dataclass
class Reply:
    text: str
    usage: dict | None = None
    finish_reason: str | None = None


Call = Callable[[str, str], Awaitable[Reply]]


class LLMError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


class QuotaExhausted(LLMError):
    """The provider asks for a longer wait than a run should sleep: a daily quota."""


async def llm_call(system: str, user: str) -> Reply:
    from detection.llm import llm_call as detection_llm_call

    return Reply(await detection_llm_call(user, system) or "")


def openai_call(max_completion_tokens: int = 2048, reasoning_effort: str | None = None,
                transport: httpx.AsyncBaseTransport | None = None, *,
                model_name: str | None = None, url: str | None = None,
                api_key: str | None = None) -> Call:
    """detection's ollama request (OpenAI-style body, Bearer LLM_API_KEY, LLM_URL,
    PER_CALL_TIMEOUT_SECONDS), with its own max_completion_tokens and reasoning_effort.
    llm_call's fixed max_tokens of 1024 let a reasoning model spend the whole cap on
    reasoning and return an empty reply; 2048 leaves room for the answer.
    Every credential/address falls back from PROPOSAL_LLM_* to the shared LLM_*
    value, so the deck can run a separate model on a separate key. Explicit
    model_name / url / api_key arguments beat the env chain (the verifier uses
    them to bind its own model)."""
    async def call(system: str, user: str) -> Reply:
        endpoint = url or _setting("LLM_URL")
        model = model_name or _setting("LLM_MODEL")
        key = (api_key if api_key is not None
               else (os.environ.get("PROPOSAL_LLM_API_KEY")
                     or os.environ.get("LLM_API_KEY") or ""))
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": model, "max_completion_tokens": max_completion_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        # Deck calls run against slow instruct/reasoning models: two minutes
        # per call, not research's 8-second search budget.
        timeout = int(os.environ.get("PER_CALL_TIMEOUT_SECONDS", "120"))
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]
        return Reply(choice["message"].get("content") or "", data.get("usage"),
                     choice.get("finish_reason"))
    return call


def _setting(shared_name: str) -> str:
    """A required LLM_* value, first from its PROPOSAL_LLM_* override.

    An empty override (docker-compose passes unset ones as '') counts as no
    override, so the shared .env value - unchanged project-wide behavior - is
    what a deployment gets by default."""
    value = os.environ.get(f"PROPOSAL_{shared_name}") or os.environ.get(shared_name)
    if not value:
        raise KeyError(shared_name)  # same failure plain [shared_name] access had
    return value


def _retry_after(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return 5.0


def _message(resp: httpx.Response) -> str:
    try:
        return str(resp.json()["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError):
        return resp.text[:300]


@dataclass
class Adapter:
    call: Call = llm_call
    min_interval_s: float = 2.0  # Groq allows 30 requests per minute
    max_wait_s: float = 120.0
    max_retries: int = 3
    max_429: int = 20
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    calls: list[dict] = field(default_factory=list)
    model_name: str = ""  # set when this adapter is bound to one model (the verifier's)
    _last_start: float = field(default=float("-inf"), init=False, repr=False)

    def __call__(self, system: str, user: str) -> str:
        rec = {"step": next((k for k, v in TASKS.items() if system.endswith(v)), None),
               "model": self.model_name,
               "rate_limited": 0, "retries": 0, "waited_s": 0.0}
        while True:
            gap = self._last_start + self.min_interval_s - self.clock()
            if gap > 0:
                self.sleep(gap)
            self._last_start = start = self.clock()
            try:
                reply = asyncio.run(self.call(system, user))
            except httpx.HTTPStatusError as e:
                status, message = e.response.status_code, _message(e.response)
                if status == 429:
                    wait = _retry_after(e.response)
                    if wait > self.max_wait_s or rec["rate_limited"] == self.max_429:
                        raise QuotaExhausted(status, message) from None
                    rec["rate_limited"] += 1
                    rec["waited_s"] += wait
                    self.sleep(wait)
                    continue
                if status < 500 or rec["retries"] == self.max_retries:
                    raise LLMError(status, message) from None
            except httpx.TransportError as e:
                if rec["retries"] == self.max_retries:
                    raise LLMError(None, f"{type(e).__name__} after {self.max_retries} retries") \
                        from None
            else:
                rec.update(latency_s=round(self.clock() - start, 3), usage=reply.usage,
                           finish_reason=reply.finish_reason, user=user, reply=reply.text)
                self.calls.append(rec)
                return reply.text
            rec["retries"] += 1
            backoff = 2.0 ** rec["retries"]
            rec["waited_s"] += backoff
            self.sleep(backoff)


def verifier_call() -> tuple[str, Adapter] | tuple[None, None]:
    """The grounding verifier's own model and its Adapter, or (None, None): the
    guard runs only when PROPOSAL_VERIFIER_LLM_MODEL names a model, and
    deliberately never falls back to the writer's - a same-model check is no
    different-model guard. Its URL and key fall back to the proposal's, then
    the shared ones, so usually only the model id is new."""
    model = os.environ.get("PROPOSAL_VERIFIER_LLM_MODEL") or ""
    if not model:
        return None, None
    url = (os.environ.get("PROPOSAL_VERIFIER_LLM_URL")
           or os.environ.get("PROPOSAL_LLM_URL")
           or os.environ.get("LLM_URL") or "")
    key = (os.environ.get("PROPOSAL_VERIFIER_LLM_API_KEY")
           or os.environ.get("PROPOSAL_LLM_API_KEY")
           or os.environ.get("LLM_API_KEY") or "")
    adapter = Adapter(call=openai_call(512, None, url=url or None, api_key=key or None),
                      model_name=model)
    return model, adapter


def same_model_note(model: str) -> str | None:
    """The operator ran the verifier on the writer's model; say so once."""
    writer = os.environ.get("PROPOSAL_LLM_MODEL") or os.environ.get("LLM_MODEL") or ""
    if writer and writer.lower() == model.lower():
        return (f"the grounding verifier uses the writer's model ({model}); "
                "its rulings may share the writer's blind spots")
    return None
