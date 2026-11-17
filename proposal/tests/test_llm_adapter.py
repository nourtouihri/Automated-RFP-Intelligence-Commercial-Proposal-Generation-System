import asyncio
import json

import httpx
import pytest

import detection.llm
from proposal.compose import TASKS
from proposal.llm_adapter import Adapter, LLMError, QuotaExhausted, Reply, openai_call

SYSTEM = "rules\nTASK: " + TASKS["brief"]
URL = "https://llm.example.test/v1/chat/completions"


class FakeTime:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def status_error(code, retry_after=None, message="slow down"):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    request = httpx.Request("POST", URL, headers={"Authorization": "Bearer sk-secret"})
    response = httpx.Response(code, headers=headers, json={"error": {"message": message}},
                              request=request)
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)


def scripted(*outcomes):
    """An llm call that raises or answers each outcome in turn."""
    seen = []

    async def call(system, user):
        seen.append((system, user))
        out = outcomes[len(seen) - 1]
        if isinstance(out, Exception):
            raise out
        return Reply(out)
    return call, seen


def adapter(call, t=None, **kw):
    t = t or FakeTime()
    return Adapter(call=call, sleep=t.sleep, clock=t.clock, **kw)


def test_llm_call_gets_the_prompt_first_and_the_system_second(monkeypatch):
    seen = {}

    async def fake(prompt, system=None):
        seen.update(prompt=prompt, system=system)
        return '{"ok": 1}'
    monkeypatch.setattr(detection.llm, "llm_call", fake)
    t = FakeTime()
    assert Adapter(sleep=t.sleep, clock=t.clock)("SYS", "USER") == '{"ok": 1}'
    assert seen == {"prompt": "USER", "system": "SYS"}


def test_a_429_is_waited_out_with_retry_after():
    call, seen = scripted(status_error(429, retry_after=7), "{}")
    t = FakeTime()
    a = adapter(call, t)
    assert a(SYSTEM, "u") == "{}"
    assert t.slept == [7.0] and len(seen) == 2
    assert a.calls[0]["step"] == "brief" and a.calls[0]["rate_limited"] == 1


def test_a_daily_quota_stops_the_run_without_leaking_the_key():
    call, _ = scripted(status_error(429, retry_after=3600, message="tokens per day (TPD)"))
    with pytest.raises(QuotaExhausted) as e:
        adapter(call)(SYSTEM, "u")
    assert e.value.status == 429 and "tokens per day" in str(e.value)
    assert "sk-secret" not in str(e.value) and e.value.__cause__ is None


def test_other_client_errors_fail_fast_with_status_and_message():
    call, seen = scripted(status_error(401, message="Invalid API Key"))
    with pytest.raises(LLMError, match="HTTP 401: Invalid API Key"):
        adapter(call)(SYSTEM, "u")
    assert len(seen) == 1


def test_timeouts_and_server_errors_are_retried_with_backoff():
    call, _ = scripted(httpx.ReadTimeout("slow"), status_error(503), "{}")
    a = adapter(call)
    assert a(SYSTEM, "u") == "{}"
    assert a.calls[0]["retries"] == 2


def test_calls_are_spaced():
    call, _ = scripted("{}", "{}")
    t = FakeTime()
    a = adapter(call, t, min_interval_s=2.0)
    a(SYSTEM, "u")
    a(SYSTEM, "u")
    assert t.slept == [2.0]


def test_a_null_reply_reaches_compose_as_empty_text(monkeypatch):
    # A reasoning model can spend the token cap on reasoning and return no content.
    async def fake(prompt, system=None):
        return None
    monkeypatch.setattr(detection.llm, "llm_call", fake)
    t = FakeTime()
    assert Adapter(sleep=t.sleep, clock=t.clock)(SYSTEM, "u") == ""


def test_openai_call_sends_the_reasoning_effort_and_keeps_usage(monkeypatch):
    monkeypatch.setenv("LLM_URL", URL)
    monkeypatch.setenv("LLM_MODEL", "some-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content), url=str(request.url),
                    auth=request.headers["authorization"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    call = openai_call(reasoning_effort="low",
                       transport=httpx.MockTransport(handler))
    reply = asyncio.run(call("SYS", "USER"))
    assert (reply.text, reply.finish_reason, reply.usage["completion_tokens"]) == ("{}", "stop", 5)
    assert (seen["url"], seen["auth"], seen["model"]) == (URL, "Bearer test-key", "some-model")
    assert (seen["max_completion_tokens"], seen["reasoning_effort"]) == (2048, "low")
    assert "max_tokens" not in seen
    assert [m["role"] for m in seen["messages"]] == ["system", "user"]
