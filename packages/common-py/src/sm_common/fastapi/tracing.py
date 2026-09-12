"""Real per-request OpenTelemetry spans (Engineering Constitution §14; ADR-020).

`RequestContextMiddleware` (`middleware.py`) already parses `traceparent` to
derive a structlog `correlation_id`; this middleware is the actual tracing
layer — it extracts the inbound W3C context, opens a real span for the
request's lifetime, and injects the resulting context into the response
headers. With no OTel provider configured (local dev / CI without a
collector, ADR-020) the span is a no-op with an invalid context — nothing
here fabricates a trace when one was never really recorded.
"""

from __future__ import annotations

from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["TracingMiddleware"]

_tracer = trace.get_tracer("sm.http")


class TracingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        parent_ctx = propagate.extract(headers)
        method = scope.get("method", "")
        path = scope.get("path", "")

        status_holder: dict[str, int] = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                out_headers: dict[str, str] = {}
                propagate.inject(out_headers)
                if out_headers:
                    raw_headers = list(message.get("headers", []))
                    for k, v in out_headers.items():
                        raw_headers.append((k.encode("latin-1"), v.encode("latin-1")))
                    message = {**message, "headers": raw_headers}
            await send(message)

        with _tracer.start_as_current_span(
            f"{method} {path}", context=parent_ctx, kind=SpanKind.SERVER
        ) as span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.target", path)
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                status = status_holder["status"]
                span.set_attribute("http.status_code", status)
                if status >= 500:
                    span.set_status(StatusCode.ERROR)
