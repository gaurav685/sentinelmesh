"""Normalization-engine Prometheus counters, on the shared registry.

DLQ / retry / produce-error counts are the shared bus metrics
(`sm_consumer_dlq_total{group="normalization"}`, `sm_consumer_retries_total`,
`sm_producer_send_errors_total`) — not duplicated here.
"""

from __future__ import annotations

from prometheus_client import Counter

from sm_common.observability import Metrics

__all__ = ["NormalizationMetrics"]


class NormalizationMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._service = service_name
        registry = base.registry

        self.consumed = Counter(
            "sm_normalize_in_total",
            "telemetry.raw records consumed",
            ("service", "source_type"),
            registry=registry,
        )
        self.produced = Counter(
            "sm_normalize_out_total",
            "events.canonical records produced",
            ("service", "source_type"),
            registry=registry,
        )

    def consumed_inc(self, source_type: str) -> None:
        self.consumed.labels(self._service, source_type).inc()

    def produced_inc(self, source_type: str) -> None:
        self.produced.labels(self._service, source_type).inc()
