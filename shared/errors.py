"""Uniform error envelope, request-id propagation, and FastAPI wiring.

Why this shape instead of FastAPI's default ``{"detail": ...}``:

- callers (n8n workflows, the crawler) branch on stable machine-readable
  ``code`` values and on ``retryable``, without parsing prose;
- ``field`` turns a validation failure into an actionable payload fix instead
  of a support ticket;
- every response — success or failure — carries the same ``X-Request-ID``,
  so detection, research and RAG log lines can be stitched together for one
  trigger. The inbound header is echoed only when it matches a safe charset
  (never reflect arbitrary bytes into logs or responses);
- nothing escapes as a raw 500: unhandled exceptions are logged with the
  request id and rendered as an ``INTERNAL`` envelope.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from enum import Enum
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.redaction import SecretScrubber

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Bound to the current request so any nested code (LLM degrade paths, store
# warnings) can attach the request id to its log record without plumbing it
# through every function signature.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class ErrorCode(str, Enum):
    """Stable error taxonomy. Values are part of the public contract."""

    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    BAD_REQUEST = "BAD_REQUEST"
    INTERNAL = "INTERNAL"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    TENDER_INVALID_FIELD = "TENDER_INVALID_FIELD"
    TENDER_INVALID_DEADLINE = "TENDER_INVALID_DEADLINE"
    TENDER_INVALID_REQUIREMENTS = "TENDER_INVALID_REQUIREMENTS"
    RAW_TEXT_TOO_LONG = "RAW_TEXT_TOO_LONG"
    TENDER_BATCH_INVALID = "TENDER_BATCH_INVALID"
    TENDER_BATCH_TOO_LARGE = "TENDER_BATCH_TOO_LARGE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"


class ApiError(Exception):
    """Domain error rendered as the shared envelope by ``install()`` handlers.

    ``retryable`` is the n8n branch signal: a 401 or a bad payload will not
    get better on retry, a transient store/lock failure might.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        field: Optional[str] = None,
        status_code: int = 422,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.status_code = status_code
        self.retryable = retryable


def error_envelope(
    code: ErrorCode,
    message: str,
    *,
    field: Optional[str] = None,
    retryable: bool = False,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    """Always the same all-keys shape, so clients never key-error."""
    return {
        "error": {
            "code": code.value,
            "message": message,
            "field": field,
            "retryable": retryable,
            "request_id": request_id,
        }
    }


def current_request_id() -> str:
    """Request id for logging from outside a Request context (empty if none)."""
    return request_id_var.get()


def _request_id_for(request: Request) -> str:
    """Prefer the middleware-set state; fall back for handler-only tests."""
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid:
        return rid
    rid = request_id_var.get()
    return rid or uuid.uuid4().hex


def _response(request: Request, status_code: int, body: dict[str, Any]) -> JSONResponse:
    # The header is set here as well as in RequestIdMiddleware: a 500 built by
    # ServerErrorMiddleware bypasses the middleware's response path, and the
    # request id is exactly what makes those logs findable.
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={REQUEST_ID_HEADER: _request_id_for(request)},
    )


class RequestIdMiddleware:
    """ASGI middleware: validate/assign X-Request-ID, propagate, echo.

    Implemented as a pure ASGI middleware rather than BaseHTTPMiddleware:
    the latter runs the downstream app in a separate anyio task and its
    contextvar handling has changed across Starlette versions; a raw ASGI
    call keeps the contextvar set for the whole request, including exception
    handlers, with no version-sensitive behavior. It also avoids buffering
    responses, which BaseHTTPMiddleware does.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex

        # Mutate the request scope in place (not a copy): ServerErrorMiddleware
        # sits OUTSIDE this middleware, and for an unhandled 500 it renders the
        # response from its own Request(scope) — same object — so the envelope
        # must be able to read the very same request id the logs used.
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_var.set(rid)
        try:
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    message.setdefault("headers", [])
                    message["headers"] = [
                        (k, v) for (k, v) in message["headers"]
                        if k.lower() != b"x-request-id"
                    ]
                    message["headers"].append((b"x-request-id", rid.encode("ascii")))
                await send(message)

            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error(
            "ApiError(%s) on %s %s: %s",
            exc.code.value, request.method, request.url.path, exc.message,
            extra={"request_id": _request_id_for(request)},
        )
    return _response(
        request,
        exc.status_code,
        error_envelope(
            exc.code,
            exc.message,
            field=exc.field,
            retryable=exc.retryable,
            request_id=_request_id_for(request),
        ),
    )


async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI body/query validation -> the same envelope (never ``detail``)."""
    first = exc.errors()[0] if exc.errors() else {}
    location = [str(part) for part in first.get("loc", ())]
    field = ".".join(location) if location else None
    message = first.get("msg", "Request failed validation")
    return _response(
        request,
        422,
        error_envelope(
            ErrorCode.TENDER_INVALID_FIELD,
            f"Invalid request: {message}",
            field=field,
            retryable=False,
            request_id=_request_id_for(request),
        ),
    )


_HTTP_STATUS_TO_CODE = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.UNAUTHORIZED,
    404: ErrorCode.NOT_FOUND,
    422: ErrorCode.TENDER_INVALID_FIELD,
    503: ErrorCode.UPSTREAM_UNAVAILABLE,
}


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Wrap HTTPException (auth 401, missing 404, ...) in the envelope."""
    code = _HTTP_STATUS_TO_CODE.get(exc.status_code)
    if code is None:
        code = ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.BAD_REQUEST
    return _response(
        request,
        exc.status_code,
        error_envelope(
            code,
            str(exc.detail),
            retryable=exc.status_code >= 500,
            request_id=_request_id_for(request),
        ),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = _request_id_for(request)
    logger.exception(
        "Unhandled error on %s %s (request_id=%s)",
        request.method, request.url.path, rid,
        extra={"request_id": rid},
    )
    return _response(
        request,
        500,
        error_envelope(
            ErrorCode.INTERNAL,
            "Internal server error",
            retryable=True,
            request_id=rid,
        ),
    )


def install(app: FastAPI) -> None:
    """Attach middleware, exception handlers and log scrubbing. Call once, right after FastAPI()."""
    # add_middleware must happen before the middleware stack is first built
    # (first request / lifespan startup); module-level call sites satisfy that.
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    # On the loggers, not a handler, so records are scrubbed before any handler
    # sees them. An unhandled error is logged by _unhandled_exception_handler and
    # then re-raised by Starlette for uvicorn to log again on uvicorn.error;
    # either traceback can carry an upstream URL with its key (SAM.gov's api_key).
    for target in (logger, logging.getLogger("uvicorn.error")):
        if not any(isinstance(f, SecretScrubber) for f in target.filters):
            target.addFilter(SecretScrubber())
