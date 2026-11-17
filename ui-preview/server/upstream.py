from typing import Any, NoReturn

import httpx

from shared.errors import _HTTP_STATUS_TO_CODE, ApiError, ErrorCode, current_request_id

from .config import Settings

TOKEN_HEADER = "X-Internal-Token"
REQUEST_ID_HEADER = "X-Request-ID"


def _unavailable(service: str, detail: str) -> ApiError:
    return ApiError(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        f"The {service} service {detail}",
        status_code=503,
        retryable=True,
    )


def _code_for_status(status: int) -> ErrorCode:
    code = _HTTP_STATUS_TO_CODE.get(status)
    if code is not None:
        return code
    return ErrorCode.INTERNAL if status >= 500 else ErrorCode.BAD_REQUEST


def _parse_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _raise_for_failure(service: str, response: httpx.Response) -> NoReturn:
    status = response.status_code
    body = _parse_json(response)
    if isinstance(body, dict):
        envelope = body.get("error")
        if isinstance(envelope, dict) and isinstance(envelope.get("message"), str):
            try:
                code = ErrorCode(envelope.get("code"))
            except ValueError:
                code = _code_for_status(status)
            raise ApiError(
                code,
                envelope["message"],
                field=envelope.get("field"),
                status_code=status,
                retryable=bool(envelope.get("retryable", status >= 500)),
            )
        if "detail" in body:
            raise ApiError(
                _code_for_status(status),
                str(body["detail"]),
                status_code=status,
                retryable=status >= 500,
            )
    if status >= 500:
        raise _unavailable(service, f"answered {status} without a usable body.")
    raise ApiError(_code_for_status(status), f"The {service} service answered {status}.", status_code=status)


class Upstream:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._client = httpx.Client(transport=transport)

    def close(self) -> None:
        self._client.close()

    def call(
        self,
        service: str,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
        request_id: str | None = None,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        response = self._send(
            service,
            method,
            path,
            json=json,
            params=params,
            request_id=request_id,
            timeout=timeout,
            headers=headers,
        )
        if not response.is_success:
            _raise_for_failure(service, response)
        if not response.content:
            return response.status_code, None
        body = _parse_json(response)
        if body is None and response.content.strip() != b"null":
            raise _unavailable(service, "answered with something other than JSON.")
        return response.status_code, body

    def stream(self, service: str, path: str, *, request_id: str | None = None) -> httpx.Response:
        """Open a file download; the caller reads and closes the response."""
        response = self._send(service, "GET", path, request_id=request_id, stream=True)
        if not response.is_success:
            try:
                response.read()
            except httpx.HTTPError:
                raise _unavailable(service, "could not be reached.") from None
            finally:
                response.close()
            _raise_for_failure(service, response)
        return response

    def probe(self, service: str, path: str, *, timeout: float = 2.0) -> int | None:
        """Status of an unauthenticated GET, or None when the service cannot be reached."""
        try:
            response = self._client.get(self._url(service, path), timeout=timeout)
        except httpx.HTTPError:
            return None
        return response.status_code

    def _url(self, service: str, path: str) -> str:
        return self._settings.services[service] + path

    def _send(
        self,
        service: str,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
        request_id: str | None = None,
        timeout: float | None = None,
        stream: bool = False,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers = {**(headers or {}), TOKEN_HEADER: self._settings.token}
        rid = request_id or current_request_id()
        if rid:
            headers[REQUEST_ID_HEADER] = rid
        request = self._client.build_request(
            method,
            self._url(service, path),
            json=json,
            params=params,
            headers=headers,
            timeout=self._settings.timeouts["default"] if timeout is None else timeout,
        )
        try:
            return self._client.send(request, stream=stream)
        except httpx.TimeoutException:
            raise _unavailable(
                service, "did not answer in time; the work may still be running there."
            ) from None
        except httpx.HTTPError:
            raise _unavailable(service, "could not be reached.") from None
