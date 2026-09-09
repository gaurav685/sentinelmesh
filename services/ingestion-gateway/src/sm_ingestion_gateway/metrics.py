"""Ingestion-specific Prometheus counters.

They register on the shared `Metrics` registry (so `/metrics` renders them
alongside the platform metrics) but are grouped here because only this service
reports them. No value is fabricated — each is incremented on a real request.
"""

from __future__ import annotations

from prometheus_client import Counter

from sm_common.observability import Metrics

__all__ = ["IngestionMetrics"]


class IngestionMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._service = service_name
        registry = base.registry

        self.accepted = Counter(
            "sm_ingest_accepted_total",
            "Sensor events validated and handed to the raw-event sink",
            ("service", "source_type"),
            registry=registry,
        )
        self.rejected = Counter(
            "sm_ingest_rejected_total",
            "Sensor events rejected (bad JSON or failed payload schema) and dead-lettered",
            ("service", "source_type"),
            registry=registry,
        )
        self.duplicates = Counter(
            "sm_ingest_duplicates_total",
            "Ingest requests suppressed as a duplicate X-Sensor-Event-Id",
            ("service", "source_type"),
            registry=registry,
        )
        self.dedup_errors = Counter(
            "sm_ingest_dedup_errors_total",
            "Dedup checks that could not reach Redis (the event was still sinked)",
            ("service",),
            registry=registry,
        )

    def accepted_inc(self, source_type: str) -> None:
        self.accepted.labels(self._service, source_type).inc()

    def rejected_inc(self, source_type: str) -> None:
        self.rejected.labels(self._service, source_type).inc()

    def duplicate_inc(self, source_type: str) -> None:
        self.duplicates.labels(self._service, source_type).inc()

    def dedup_error_inc(self) -> None:
        self.dedup_errors.labels(self._service).inc()
