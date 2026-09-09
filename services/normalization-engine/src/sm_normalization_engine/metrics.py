"""Normalization-engine Prometheus counters, on the shared registry."""

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
        self.dead_lettered = Counter(
            "sm_normalize_dlq_total",
            "records sent to telemetry.raw.dlq",
            ("service", "reason"),
            registry=registry,
        )
        self.produce_errors = Counter(
            "sm_normalize_produce_errors_total",
            "produce attempts that failed after retries (offset not committed)",
            ("service", "topic"),
            registry=registry,
        )

    def consumed_inc(self, source_type: str) -> None:
        self.consumed.labels(self._service, source_type).inc()

    def produced_inc(self, source_type: str) -> None:
        self.produced.labels(self._service, source_type).inc()

    def dlq_inc(self, reason: str) -> None:
        self.dead_lettered.labels(self._service, reason).inc()

    def produce_error_inc(self, topic: str) -> None:
        self.produce_errors.labels(self._service, topic).inc()
