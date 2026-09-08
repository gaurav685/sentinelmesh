"""Fixed-window rate limiting (Engineering Constitution §5; security-model.md §5).

Keyed on the resolved client IP (never a spoofable header — see `clientinfo`).
A fixed one-minute window in Redis: `INCR` the bucket, `EXPIRE` it on first
touch, reject once the count passes the limit.

Failure policy for the API gateway (a read-facing service): **fail open** if the
limiter's store is unavailable, and raise `sm_rate_limiter_errors_total` so the
outage is visible. Taking the SOC UI down because Redis blinked would be worse
than briefly not rate-limiting. Ingestion, which must fail closed, will use a
different limiter in its own phase.

`/healthz`, `/readyz`, `/health/deps` and `/metrics` are never limited.

The limiter reads its Redis client and metrics from `scope["app"].state`, so it
can be registered before the lifespan builds those. The host must set
`app.state.rate_limit_redis` (an object exposing async `incr`/`expire`) and
`app.state.rate_limit_metrics` (an object exposing `.rate_limited` and
`.rate_limiter_errors` counters, each with a `.labels(service).inc()`); if either
is missing the limiter fails open.

The 429 body is rendered here directly, in the canonical error shape, because
the FastAPI exception handlers sit *below* the user middleware stack and cannot
catch an exception raised from a middleware.
"""

from __future__ import annotations

import json
import time
from uuid import uuid4

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import AppSettings
from ..context import get_correlation_id, get_request_id
from ..errors import RateLimited
from .clientinfo import client_ip

__all__ = ["RateLimitMiddleware"]

_log = structlog.get_logger("sm.ratelimit")

_EXEMPT_PATHS = frozenset({"/healthz", "/readyz", "/health/deps", "/metrics"})


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, *, settings: AppSettings, key_prefix: str = "sm") -> None:
        self.app = app
        self._limit = settings.rate_limit_per_minute
        self._hops = settings.trusted_proxy_hops
        self._prefix = key_prefix
        self._service = settings.service_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if request.url.path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        state = getattr(scope.get("app"), "state", None)
        redis = getattr(state, "rate_limit_redis", None)
        metrics = getattr(state, "rate_limit_metrics", None)
        if redis is None:
            await self.app(scope, receive, send)
            return

        ip = client_ip(request, self._hops) or "unknown"
        window = int(time.time() // 60)
        key = f"{self._prefix}:ratelimit:{ip}:{window}"

        try:
            count = int(await redis.incr(key))
            if count == 1:
                await redis.expire(key, 65)
        except Exception:
            if metrics is not None:
                metrics.rate_limiter_errors.labels(self._service).inc()
            _log.warning("rate_limiter_unavailable", client_ip=ip)
            await self.app(scope, receive, send)
            return

        if count > self._limit:
            if metrics is not None:
                metrics.rate_limited.labels(self._service).inc()
            _log.info("rate_limited", client_ip=ip, count=count, limit=self._limit)
            await self._send_429(send, retry_after=60 - int(time.time() % 60))
            return

        await self.app(scope, receive, send)

    async def _send_429(self, send: Send, *, retry_after: int) -> None:
        err = RateLimited()
        body = json.dumps(
            {
                "error": {
                    "code": str(err.code),
                    "message": err.message,
                    "request_id": str(get_request_id() or uuid4()),
                    "correlation_id": str(get_correlation_id() or uuid4()),
                    "details": [],
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": err.http_status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
