"""OpenTelemetry tracing bootstrap (Engineering Constitution §14; ADR-020).

`configure_tracing(settings)` is a no-op when `SM_OTEL_EXPORTER_OTLP_ENDPOINT` is
unset or `SM_OTEL_TRACES_ENABLED` is false — local dev and CI run without a
collector and must not fail or block on one. When an endpoint is configured, an
OTLP/HTTP span exporter is installed with a batch processor.

Without a configured provider, `trace.get_tracer()` falls back to the OTel
API's default no-op tracer: spans it creates carry an *invalid* span context
(`is_valid` is `False`). `current_trace_id()` checks this explicitly — it
returns `None` rather than a fabricated id whenever there is no real span.

`trace_id` flows through the event envelope so async hops stay correlated
(`sm_common.fastapi.TracingMiddleware` sets it from the inbound HTTP span;
`sm_common.bus.RecordProcessor` reconstructs a remote parent context from it
via `remote_context_from_trace_id` so a Kafka-consumer span links back to the
same trace, not a fresh disconnected one).
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    set_span_in_context,
)

from ..config import AppSettings

__all__ = [
    "configure_tracing",
    "current_trace_id",
    "get_tracer",
    "remote_context_from_trace_id",
    "shutdown_tracing",
]

_provider: TracerProvider | None = None


def configure_tracing(settings: AppSettings) -> None:
    global _provider
    if not settings.otel_traces_enabled or not settings.otel_exporter_otlp_endpoint:
        return
    if _provider is not None:
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    resource = Resource.create(
        {"service.name": settings.service_name, "deployment.environment": str(settings.env)}
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    """The active span's trace-id as 32 lowercase hex chars, or `None` if there
    is no real (recording or remote) span — e.g. no OTel provider configured."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


def remote_context_from_trace_id(trace_id: str | None) -> Context | None:
    """Build a remote parent `Context` from a bare trace-id string (the shape
    the event envelope carries — not a full W3C `traceparent`, so there is no
    real parent span-id to restore). A span started with this context links to
    the same trace as a genuine child, even though the exact producer span is
    unknown. Returns `None` for a missing/malformed id so the caller starts a
    fresh, disconnected span instead of fabricating a link."""
    if not trace_id:
        return None
    try:
        trace_id_int = int(trace_id, 16)
    except ValueError:
        return None
    if trace_id_int == 0:
        return None
    span_context = SpanContext(
        trace_id=trace_id_int,
        span_id=trace.INVALID_SPAN_ID + 1,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(span_context))


def shutdown_tracing() -> None:
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
