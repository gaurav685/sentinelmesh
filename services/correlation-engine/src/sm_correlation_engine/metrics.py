"""correlation-engine Prometheus metrics (shared registry)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge

from sm_common.observability import Metrics

__all__ = ["CorrelationMetrics"]


class CorrelationMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._s = service_name
        reg = base.registry
        self.detections = Counter(
            "sm_correlation_detections_total", "detections processed for correlation",
            ("service", "stage"), registry=reg,
        )
        self.chains_created = Counter(
            "sm_correlation_chains_created_total", "new attack chains opened", ("service",), registry=reg,
        )
        self.chains_updated = Counter(
            "sm_correlation_chains_updated_total", "existing attack chains updated",
            ("service",), registry=reg,
        )
        self.new_detections = Counter(
            "sm_correlation_new_detections_total", "detections newly added to a chain stage "
            "(a redelivery of one already present does not count)",
            ("service", "stage"), registry=reg,
        )
        self.chain_status = Gauge(
            "sm_correlation_chain_status", "1 for the current status of the last-updated chain",
            ("service", "status"), registry=reg,
        )

    def detection(self, stage: str) -> None:
        self.detections.labels(self._s, stage).inc()

    def chain(self, *, created: bool, new_detection: bool, status: str, stage: str) -> None:
        if created:
            self.chains_created.labels(self._s).inc()
        else:
            self.chains_updated.labels(self._s).inc()
        if new_detection:
            self.new_detections.labels(self._s, stage).inc()
        for candidate in ("forming", "active", "dormant"):
            self.chain_status.labels(self._s, candidate).set(1 if candidate == status else 0)
