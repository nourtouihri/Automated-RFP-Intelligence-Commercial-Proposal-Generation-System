"""The agent's own LLM client.

Same shape as the team's function: async llm_call(text, system=None) -> str.

Provider is chosen by INSIGHTS_LLM_PROVIDER: anthropic | openai | groq | ollama.
If it is not set, the team's detection.llm.llm_call is used instead.
Keys are read from the environment and never logged.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

TIMEOUT_S = 60.0
MAX_TOKENS = 2048
ERROR_BODY_CHARS = 300

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "ollama": "llama3.1",
}


class LLMConfigError(RuntimeError):
    """Missing key or unknown provider."""


class LLMProviderError(RuntimeError):
    """The provider answered with an HTTP error. Carries its own explanation."""


async def _post(url: str, headers: dict, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            # The provider's explanation (model not found, bad key, rate limit...).
            # Only the response body is included, never the request headers (the key).
            raise LLMProviderError(
                f"LLM provider error {resp.status_code}: {resp.text[:ERROR_BODY_CHARS]}"
            )
        return resp.json()


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LLMConfigError(f"{name} is not set")
    return value


def _chat_messages(text: str, system: Optional[str]) -> list[dict]:
    return ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": text}
    ]


async def _anthropic(text: str, system: Optional[str], model: str) -> str:
    payload: dict = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": text}],
    }
    if system:
        payload["system"] = system
    data = await _post(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": _require("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
        payload,
    )
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


async def _openai(text: str, system: Optional[str], model: str) -> str:
    data = await _post(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {_require('OPENAI_API_KEY')}"},
        {"model": model, "max_tokens": MAX_TOKENS, "messages": _chat_messages(text, system)},
    )
    return data["choices"][0]["message"]["content"] or ""


async def _groq(text: str, system: Optional[str], model: str) -> str:
    data = await _post(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {_require('GROQ_API_KEY')}"},
        {"model": model, "max_tokens": MAX_TOKENS, "messages": _chat_messages(text, system)},
    )
    return data["choices"][0]["message"]["content"] or ""


async def _ollama(text: str, system: Optional[str], model: str) -> str:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    data = await _post(
        f"{base}/api/chat",
        {},
        {
            "model": model,
            "messages": _chat_messages(text, system),
            "stream": False,
            "format": "json",
        },
    )
    return data.get("message", {}).get("content", "")


_PROVIDERS = {"anthropic": _anthropic, "openai": _openai, "groq": _groq, "ollama": _ollama}


def provider_name() -> str:
    return os.environ.get("INSIGHTS_LLM_PROVIDER", "").strip().lower()


async def default_llm_call(text: str, system: Optional[str] = None) -> str:
    """The agent's default LLM. Own provider if configured, else the team's."""
    name = provider_name()
    if not name:
        from detection.llm import llm_call as team_llm_call  # lazy

        return await team_llm_call(text, system=system)
    fn = _PROVIDERS.get(name)
    if fn is None:
        raise LLMConfigError(f"unknown INSIGHTS_LLM_PROVIDER {name!r}")
    model = os.environ.get("INSIGHTS_LLM_MODEL", "").strip() or DEFAULT_MODELS[name]
    return await fn(text, system, model)