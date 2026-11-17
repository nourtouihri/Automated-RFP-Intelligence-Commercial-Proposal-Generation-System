import asyncio
import os
import re
from dataclasses import dataclass


@dataclass
class SearchResult:
    url: str
    content: str


class SearchAuthError(RuntimeError):
    """401/403: the search credential is rejected; retrying cannot help."""


class SearchRateLimitError(RuntimeError):
    """429: rate limited. Carries the server's ``Retry-After`` when present."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__(f"search API rate limited (Retry-After={retry_after})")
        self.retry_after = retry_after


def clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _per_call_timeout() -> float:
    try:
        return float(os.environ.get("PER_CALL_TIMEOUT_SECONDS", "8"))
    except ValueError:
        return 8.0


def _is_retryable(exc: BaseException) -> bool:
    """Timeouts and 5xx/network errors retry once; 4xx fail fast."""
    import httpx

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    if isinstance(exc, httpx.HTTPError):
        return True
    # Unknown SDK errors (no status): treat as transient, bounded by timeout.
    return True


def _parse_retry_after(raw: str | None) -> float | None:
    """Seconds form only; an HTTP-date Retry-After is treated as unknown."""
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _sdk_errors() -> dict[str, type[BaseException]]:
    """tavily-python's 4xx classes, or ``{}`` when the SDK isn't installed.

    The SDK translates HTTP status to its *own* exception types
    (``tavily/async_tavily.py:_handle_error_response``: 429 ->
    UsageLimitExceededError, 403/432/433 -> ForbiddenError, 401 ->
    InvalidAPIKeyError, 400 -> BadRequestError) and never raises
    httpx.HTTPStatusError for 4xx. Without this map the API-key path answers a
    rejected credential with an empty result list instead of an auth error.
    """
    try:
        from tavily.errors import (
            BadRequestError,
            ForbiddenError,
            InvalidAPIKeyError,
            UsageLimitExceededError,
        )
    except ImportError:
        return {}
    return {
        "bad_request": BadRequestError,
        "forbidden": ForbiddenError,
        "invalid_key": InvalidAPIKeyError,
        "rate_limit": UsageLimitExceededError,
    }


def _is_client_error(exc: BaseException) -> bool:
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return 400 <= exc.response.status_code < 500
    sdk = _sdk_errors()
    return bool(sdk) and isinstance(exc, tuple(sdk.values()))


def _classify_client_error(exc: BaseException) -> BaseException | None:
    """Map a 4xx to a typed search error the Runner can act on.

    Auth (401/403) and rate limits (429) are 4xx but need different handling
    from a plain bad request: the first says "stop, do not retry", the second
    says "wait for Retry-After if it fits the budget". Everything else stays a
    generic client error and is re-raised unchanged — on both transports.
    """
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return SearchAuthError(f"search credential rejected (HTTP {status})")
        if status == 429:
            raw = exc.response.headers.get("Retry-After")
            return SearchRateLimitError(_parse_retry_after(raw))
        return None

    sdk = _sdk_errors()
    if not sdk:
        return None
    if isinstance(exc, (sdk["forbidden"], sdk["invalid_key"])):
        return SearchAuthError(
            f"search credential rejected ({type(exc).__name__})"
        )
    if isinstance(exc, sdk["rate_limit"]):
        # TavilyKeylessLimitError carries retry_after_seconds; the API-key
        # UsageLimitExceededError does not, so that path can only degrade.
        return SearchRateLimitError(getattr(exc, "retry_after_seconds", None))
    return None


class SearchTool:
    def __init__(self, max_results: int = 3):
        self.max_results = min(max(1, max_results), 3)

    async def _sdk_search(self, query: str, api_key: str) -> list[SearchResult]:
        """Tavily SDK path, bounded by the per-call timeout with one retry."""
        from tavily import AsyncTavilyClient

        timeout = _per_call_timeout()
        last_exc: BaseException | None = None
        for attempt in range(2):
            try:
                client = AsyncTavilyClient(api_key=api_key)
                resp = await asyncio.wait_for(
                    client.search(
                        query,
                        max_results=self.max_results,
                        include_answer=False,
                        include_raw_content=False,
                    ),
                    timeout=timeout,
                )
                out: list[SearchResult] = []
                for item in (resp.get("results") or [])[: self.max_results]:
                    url = str(item.get("url", ""))
                    content = clean_text(str(item.get("content", "")))
                    if url and content:
                        out.append(SearchResult(url=url, content=content))
                return out
            except Exception as exc:  # noqa: BLE001 — classified below
                typed = _classify_client_error(exc)
                if typed is not None:
                    raise typed from exc
                if _is_client_error(exc):
                    raise
                last_exc = exc
                if not _is_retryable(exc) or attempt == 1:
                    return []  # transient exhausted: degrade, never hang the run
                await asyncio.sleep(0.5 * (attempt + 1))
        assert last_exc is not None
        return []

    async def search(self, query: str) -> list[SearchResult]:
        """Uses Tavily to search. Every call is bounded by the per-call
        timeout, with one retry-with-backoff on timeout/5xx and no retry
        on 4xx."""
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return []
        try:
            from tavily import AsyncTavilyClient  # noqa: F401
        except ImportError:
            return await self._http_search(query, api_key)
        return await self._sdk_search(query, api_key)

    async def _http_search(self, query: str, api_key: str) -> list[SearchResult]:
        import httpx

        timeout = _per_call_timeout()
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        headers={"Content-Type": "application/json"},
                        json={
                            "api_key": api_key,
                            "query": query,
                            "max_results": self.max_results,
                            "include_answer": False,
                            "include_raw_content": False,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                out: list[SearchResult] = []
                for item in (data.get("results") or [])[: self.max_results]:
                    url = str(item.get("url", ""))
                    content = clean_text(str(item.get("content", "")))
                    if url and content:
                        out.append(SearchResult(url=url, content=content))
                return out
            except Exception as exc:  # noqa: BLE001 — classified below
                typed = _classify_client_error(exc)
                if typed is not None:
                    raise typed from exc
                if _is_client_error(exc):
                    raise
                if not _is_retryable(exc) or attempt == 1:
                    return []  # transient exhausted: degrade, never hang the run
                await asyncio.sleep(0.5 * (attempt + 1))
        return []
