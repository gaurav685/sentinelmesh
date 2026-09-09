"""stream-processor Prometheus counters (on the shared registry).

Retry / DLQ / lag / send-error counts are the shared bus metrics
(`sm_consumer_*`, `sm_producer_send_errors_total`) — not duplicated here.
"""

from __future__ import annotations

from prometheus_client import Counter

from sm_common.observability import Metrics

__all__ = ["StreamMetrics"]


class StreamMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._service = service_name
        registry = base.registry
        self.consumed = Counter(
            "sm_stream_in_total",
            "events.canonical records consumed",
            ("service", "kind"),
            registry=registry,
        )
        self.commands = Counter(
            "sm_stream_commands_out_total",
            "graph.command records produced",
            ("service", "op"),
            registry=registry,
        )

    def consumed_inc(self, kind: str) -> None:
        self.consumed.labels(self._service, kind).inc()

    def command_inc(self, op: str) -> None:
        self.commands.labels(self._service, op).inc()
