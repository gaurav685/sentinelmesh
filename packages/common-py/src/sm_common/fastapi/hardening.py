"""HTTP hardening (Engineering Constitution §5, security-model.md §5).

- `SecurityHeadersMiddleware`: adds restrictive response headers.
- `BodySizeLimitMiddleware`: rejects bodies over `SM_HTTP_MAX_BODY_BYTES` with 413
  (canonical error), before the body is buffered.
- `build_cors_kwargs`: builds CORS settings from config; refuses a wildcard origin
  in production.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import AppSettings
from ..errors import PayloadTooLarge

__all__ = ["BodySizeLimitMiddleware", "SecurityHeadersMiddleware", "build_cors_kwargs"]

_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self._extra = list(_SECURITY_HEADERS)
        if hsts:
            self._extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in self._extra if k not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        seen = 0

        async def receive_capped() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise PayloadTooLarge()
            return message

        try:
            await self.app(scope, receive_capped, send)
        except PayloadTooLarge:
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        err = PayloadTooLarge()
        payload = json.dumps(
            {
                "error": {
                    "code": str(err.code),
                    "message": err.message,
                    "request_id": "00000000-0000-0000-0000-000000000000",
                    "correlation_id": "00000000-0000-0000-0000-000000000000",
                    "details": [],
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": err.http_status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})


def build_cors_kwargs(settings: AppSettings) -> dict[str, object]:
    origins = settings.cors_origins_list
    if settings.is_production and "*" in origins:
        raise ValueError("CORS wildcard origin is not allowed in production")
    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["authorization", "content-type", "x-request-id", "x-csrf-token"],
        "expose_headers": ["x-request-id"],
        "max_age": 600,
    }
