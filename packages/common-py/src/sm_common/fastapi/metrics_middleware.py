"""Real per-request HTTP metrics (Engineering Constitution §14; ADR-020).

`sm_common.observability.Metrics.observe_http` existed since an earlier
phase but nothing ever called it — `sm_http_requests_total` /
`sm_http_request_duration_seconds` were declared, scraped, and dashboarded
(Phase 15 Unit 4's Grafana panel) but never actually incremented anywhere
in the platform. Found by running the real dashboard against a real
running service and seeing an empty panel, not by reading the code.

Reads `services.metrics` from `request.app.state` (`scope["app"]`) at
request time rather than at middleware construction — `app.state.services`
is only populated once `lifespan` starts, which happens after
`app.add_middleware(...)` runs, so the metrics object cannot be injected
as a constructor argument the way it is for a route dependency.

Known narrow gap (verified, not assumed): every real error a route raises
on purpose — a `SmError` (`NotFound`, `PermissionDenied`, ...), a validation
error, an HTTP exception — is observed with its real status code, since
`install_exception_handlers`'s typed handlers send their response through
this middleware's own `send` wrapper. A genuinely *unhandled* `Exception`
(a real bug) is still recorded, but as status `0` rather than the `500` the
client actually receives — Starlette's catch-all `@app.exception_handler
(Exception)` reaches the client through a path this wrapper does not see.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["MetricsMiddleware"]


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            asgi_app = scope.get("app")
            services = getattr(getattr(asgi_app, "state", None), "services", None)
            metrics = getattr(services, "metrics", None)
            if metrics is not None:
                metrics.observe_http(method, path, status_holder["status"], time.perf_counter() - start)
