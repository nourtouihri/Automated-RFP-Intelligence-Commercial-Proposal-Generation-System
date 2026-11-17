"""Async HTTP client for the OliveSoft services.

One place that calls a service, adds the internal token and a request ID, and turns every
failure into an UpstreamError whose message is safe to show an agent: it names the service
and the next step, and never contains a URL, the token or a stack trace.

Environment (same names as the ui-preview proxy):
  INTERNAL_SERVICE_TOKEN                       shared secret, sent as X-Internal-Token
  UIP_DETECTION_URL, UIP_RAG_URL, UIP_RESEARCH_URL, UIP_PROPOSAL_URL,
  UIP_INGESTION_URL, UIP_N8N_URL               default http://localhost:8000/8001/8002/8003/8004/5678
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx

DEFAULT_URLS = {
    "detection": "http://localhost:8000",
    "rag": "http://localhost:8001",
    "research": "http://localhost:8002",
    "proposal": "http://localhost:8003",
    "ingestion": "http://localhost:8004",
    "n8n": "http://localhost:5678",
}
HEALTH_PATH = {"n8n": "/healthz"}
READ_TIMEOUT = 30.0
HEALTH_TIMEOUT = 2.0


@dataclass(frozen=True)
class Settings:
    token: str = ""
    services: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_URLS))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        services = {
            name: env.get(f"UIP_{name.upper()}_URL", url).rstrip("/")
            for name, url in DEFAULT_URLS.items()
        }
        return cls(token=env.get("INTERNAL_SERVICE_TOKEN", ""), services=services)


class UpstreamError(Exception):
    """A failure already phrased for an agent (str(e) is safe to return)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 request_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.request_id = request_id

    def __str__(self) -> str:
        suffix = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.message}{suffix}"


class Upstream:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            # follow_redirects stays off: a service never needs to redirect us elsewhere.
            self._http = httpx.AsyncClient(transport=self._transport, follow_redirects=False)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _scrub(self, text: str) -> str:
        token = self.settings.token
        return text.replace(token, "***") if token and len(token) >= 4 else text

    async def call(self, service: str, method: str, path: str, *, json: Any = None,
                   params: Mapping[str, Any] | None = None, timeout: float = READ_TIMEOUT,
                   not_found: str | None = None) -> Any:
        """Call one service and return its parsed JSON, or raise UpstreamError."""
        if not self.settings.token:
            raise UpstreamError(
                "UNAUTHORIZED",
                "INTERNAL_SERVICE_TOKEN is not set in the MCP server's environment. "
                "Set it to the same value the services use, then restart the server.")
        request_id = uuid.uuid4().hex
        url = self.settings.services[service] + path
        headers = {"X-Internal-Token": self.settings.token, "X-Request-ID": request_id}
        try:
            resp = await self._client().request(
                method, url, json=json, params=params, headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            raise UpstreamError(
                "UPSTREAM_UNAVAILABLE",
                f"The {service} service did not answer in {timeout:.0f} s. It may still be working; "
                "retry in a moment.", retryable=True, request_id=request_id) from None
        except httpx.HTTPError:
            raise UpstreamError(
                "UPSTREAM_UNAVAILABLE",
                f"The {service} service is not reachable. Run olivesoft_check_services, make sure "
                "the stack is up (docker compose up), then retry.",
                retryable=True, request_id=request_id) from None
        if resp.status_code < 300:
            try:
                return resp.json()
            except ValueError:
                raise UpstreamError(
                    "INTERNAL", f"The {service} service answered with a body that is not JSON.",
                    request_id=request_id) from None
        raise self._error(service, resp, request_id, not_found)

    def _error(self, service: str, resp: httpx.Response, request_id: str,
               not_found: str | None) -> UpstreamError:
        code, message, retryable = None, None, resp.status_code >= 500
        try:
            body = resp.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("error"), dict):  # the shared envelope
            env = body["error"]
            code, message = env.get("code"), env.get("message")
            retryable = bool(env.get("retryable", retryable))
            request_id = env.get("request_id") or request_id
        elif isinstance(body, dict) and "detail" in body:  # a raw FastAPI error
            detail = body["detail"]
            message = detail if isinstance(detail, str) else "; ".join(
                str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
        if resp.status_code == 401:
            return UpstreamError(
                "UNAUTHORIZED",
                f"The {service} service rejected the token. INTERNAL_SERVICE_TOKEN must match the "
                "value the stack runs with.", request_id=request_id)
        if resp.status_code == 404 and not_found:
            return UpstreamError("NOT_FOUND", not_found, request_id=request_id)
        if message is None:  # HTML 502 from a proxy, or an empty body
            message = ("is unavailable" if resp.status_code >= 500 else
                       f"rejected the request (HTTP {resp.status_code})")
            message = f"The {service} service {message}."
            code = code or ("UPSTREAM_UNAVAILABLE" if resp.status_code >= 500 else "BAD_REQUEST")
        else:
            message = f"{service} service: {self._scrub(str(message))[:500]}"
        return UpstreamError(code or "BAD_REQUEST", message, retryable=retryable,
                             request_id=request_id)

    async def health(self) -> list[dict[str, Any]]:
        """Liveness of every service, in parallel. /health needs no token."""
        async def one(name: str) -> dict[str, Any]:
            url = self.settings.services[name] + HEALTH_PATH.get(name, "/health")
            try:
                r = await self._client().get(url, timeout=HEALTH_TIMEOUT)
                return {"service": name, "up": r.status_code < 300, "status": r.status_code}
            except httpx.HTTPError:
                return {"service": name, "up": False, "status": None}

        return list(await asyncio.gather(*(one(n) for n in self.settings.services)))
