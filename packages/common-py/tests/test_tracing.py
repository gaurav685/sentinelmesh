from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sm_common.observability.tracing import current_trace_id, remote_context_from_trace_id


def test_current_trace_id_is_none_with_no_active_span() -> None:
    # The module-level global tracer provider is the OTel API's default
    # no-op provider unless a real one has been installed — exactly the
    # local-dev/CI-without-a-collector case ADR-020 requires.
    assert current_trace_id() is None


def test_current_trace_id_reads_a_real_active_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("unit-test-span"):
        trace_id = current_trace_id()

    assert trace_id is not None
    assert len(trace_id) == 32
    int(trace_id, 16)  # must be valid hex
    finished = exporter.get_finished_spans()
    assert format(finished[0].context.trace_id, "032x") == trace_id


def test_remote_context_from_trace_id_none_cases() -> None:
    assert remote_context_from_trace_id(None) is None
    assert remote_context_from_trace_id("") is None
    assert remote_context_from_trace_id("not-hex") is None
    assert remote_context_from_trace_id("0" * 32) is None  # all-zero trace-id is invalid


def test_remote_context_from_trace_id_builds_a_valid_remote_parent() -> None:
    trace_id = "aa" * 16
    ctx = remote_context_from_trace_id(trace_id)
    assert ctx is not None
    span = trace.get_current_span(ctx)
    span_ctx = span.get_span_context()
    assert span_ctx.is_valid
    assert span_ctx.is_remote is True
    assert format(span_ctx.trace_id, "032x") == trace_id
