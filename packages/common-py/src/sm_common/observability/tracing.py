"""OpenTelemetry tracing bootstrap (Engineering Constitution §14; ADR-020).

`configure_tracing(settings)` is a no-op when `SM_OTEL_EXPORTER_OTLP_ENDPOINT` is
unset or `SM_OTEL_TRACES_ENABLED` is false — local dev and CI run without a
collector and must not fail or block on one. When an endpoint is configured, an
OTLP/HTTP span exporter is installed with a batch processor.

`trace_id` flows through the event envelope so async hops stay correlated.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..config import AppSettings

__all__ = ["configure_tracing", "get_tracer", "shutdown_tracing"]

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


def shutdown_tracing() -> None:
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
