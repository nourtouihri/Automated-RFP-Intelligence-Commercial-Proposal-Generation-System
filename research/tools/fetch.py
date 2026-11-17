"""SSRF-guarded URL fetch tool.

The model chooses the URLs, so the tool itself must be the backstop:
- only http(s) schemes (reject file://, gopher://, ftp://, ...),
- DNS resolution is checked and private / loopback / link-local / reserved
  IPs are refused (blocks 127.0.0.1, 10/8, 172.16/12, 192.168/16, 169.254/8,
  ::1, fc00::/7, fe80::/10, ...),
- response body is capped at FETCH_MAX_BYTES (default 256 KiB) or the caller's
  ``max_bytes``,
- redirects are never followed: a 3xx raises FetchError instead of fetching an
  unvalidated Location (a redirect to 169.254.169.254 or 127.0.0.1 would
  otherwise bypass every check above),
"""

import asyncio
import ipaddress
import json
import os
import socket
from urllib.parse import urlparse
import httpx
from typing import Literal
from egressweave import EgressPolicy, build_egress_http_client, EgressNotAllowedError

FETCH_MAX_BYTES = 256 * 1024


class FetchError(ValueError):
    """Raised for blocked URLs (SSRF guard) or failed fetches."""


def _timeout() -> float:
    try:
        return float(os.environ.get("PER_CALL_TIMEOUT_SECONDS", "8"))
    except ValueError:
        return 8.0


def _max_bytes() -> int:
    try:
        return int(os.environ.get("FETCH_MAX_BYTES", str(FETCH_MAX_BYTES)))
    except ValueError:
        return FETCH_MAX_BYTES

async def fetch_url(
    url: str,
    method: Literal["GET", "POST"]= "GET",
    params:dict |None = None,
    json_body: dict | None = None,
    max_bytes: int | None = None,
) -> str:
    """Fetch a URL's response. Would fail if it's not SSRF-guarded.

    ``json_body`` is optional; when given it is serialized as the request body.
    ``max_bytes`` replaces the default body cap for this call (ingestion sizes
    its own API pages); ``None`` keeps ``FETCH_MAX_BYTES``.
    Every refusal of the guard surfaces as ``FetchError``: egressweave's
    ``EgressNotAllowedError`` (scheme/host/address violations) and hostless
    URLs (``file://``, bare words, empty ``http://`` — beyond
    ``EgressPolicy.from_hosts``) are translated here so a caller that knows
    only the documented error type handles every block the same way.
    """
    hostname = urlparse(url).hostname
    if hostname is None:
        # from_hosts cannot represent a URL with no host: refuse before it
        # raises a TypeError far from any documented contract.
        raise FetchError("Failed to fetch. The url is not safe")

    policy = EgressPolicy.from_hosts(hostname)


    timeout = httpx.Timeout(_timeout())
    cap = _max_bytes() if max_bytes is None else max_bytes
    last_exc: Exception | None = None

    try:
        normalized_url,client = await build_egress_http_client(url, policy=policy)
    except EgressNotAllowedError as exc:
        raise FetchError("Failed to fetch. The url is not safe") from exc
    if(normalized_url is None):
        raise FetchError("Failed to fetch. The url is not safe")
    try:
        # follow_redirects=False is the SSRF backstop: a 3xx is never followed, 
        # because the Location target would be fetched without re-running validate_urk and _is_hostname_allowed. 
        # The model picks the URLs, so the tool — not the caller — must decide what is reachable
        # Returning the validated URL as a redirect is the caller's cue to re-validate and re-issue explicitly.
        async with client:
            content = json.dumps(json_body) if json_body is not None else None
            headers = {"Content-Type": "application/json"} if content is not None else None
            async with client.stream(
                method,
                normalized_url,
                params=params,
                timeout=timeout,
                content=content,
                headers=headers,
            ) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location", "")
                    raise FetchError(
                        f"Blocked redirect to unvalidated location {location!r} from {url!r};"
                        f"re-issue the fetch with the validated URL"
                    )
                if 400 <= resp.status_code < 500:
                    resp.raise_for_status()
                if resp.status_code >= 500:
                    resp.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > cap:
                        break  # cap: truncate, don't fail
                    chunks.append(chunk)
                raw = b"".join(chunks)
                return raw.decode("utf-8", errors="replace")
    except FetchError:
        raise
    except httpx.HTTPStatusError as exc:
        if 400 <= exc.response.status_code < 500:
            raise FetchError(f"Fetch failed with status {exc.response.status_code}") from exc
        last_exc = exc
    except (httpx.HTTPError, asyncio.TimeoutError, TimeoutError) as exc:
        last_exc = exc
    raise FetchError(f"Fetch failed: {last_exc}")
