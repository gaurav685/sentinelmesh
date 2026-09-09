"""graph-service Prometheus counters (on the shared registry).

Retry / DLQ / lag / send-error counts are the shared bus metrics
(`sm_consumer_*`, `sm_producer_send_errors_total`) — not duplicated here.
"""

from __future__ import annotations

from prometheus_client import Counter

from sm_common.observability import Metrics

__all__ = ["GraphMetrics"]


class GraphMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._service = service_name
        self.applied = Counter(
            "sm_graph_commands_applied_total",
            "graph.commands processed, by op and outcome",
            ("service", "op", "outcome"),
            registry=base.registry,
        )

    def applied_inc(self, op: str, outcome: str) -> None:
        self.applied.labels(self._service, op, outcome).inc()
