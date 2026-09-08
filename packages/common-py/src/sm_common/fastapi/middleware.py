"""Request-context middleware.

For every inbound request:
- take the client `X-Request-Id` if it is a valid UUID, else generate one
- derive `correlation_id` from W3C `traceparent` when present, else generate one
- bind both into the ambient context (`sm_common.context`) and structlog
- echo `X-Request-Id` on the response
- log one structured access line with method, path, status, and duration
"""

from __future__ import annotations

import time
from uuid import UUID

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..context import request_context
from ..ids import new_correlation_id, new_request_id

__all__ = ["RequestContextMiddleware"]

_log = structlog.get_logger("sm.access")


def _parse_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _correlation_from_traceparent(value: str | None) -> UUID | None:
    # traceparent: "00-<32 hex trace-id>-<16 hex span-id>-<flags>"
    if not value:
        return None
    parts = value.split("-")
    if len(parts) >= 2 and len(parts[1]) == 32:
        try:
            return UUID(parts[1])
        except ValueError:
            return None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        request_id = _parse_uuid(headers.get("x-request-id")) or new_request_id()
        correlation_id = (
            _correlation_from_traceparent(headers.get("traceparent"))
            or _parse_uuid(headers.get("x-correlation-id"))
            or new_correlation_id()
        )

        method = scope.get("method", "")
        path = scope.get("path", "")
        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                raw_headers = list(message.get("headers", []))
                raw_headers.append((b"x-request-id", str(request_id).encode("latin-1")))
                message = {**message, "headers": raw_headers}
            await send(message)

        with request_context(request_id, correlation_id):
            structlog.contextvars.bind_contextvars(
                request_id=str(request_id), correlation_id=str(correlation_id)
            )
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                _log.info(
                    "request",
                    http_method=method,
                    http_path=path,
                    http_status=status_holder["status"],
                    duration_ms=duration_ms,
                )
                structlog.contextvars.unbind_contextvars("request_id", "correlation_id")
