"""mitre-service Prometheus metrics (shared registry)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge

from sm_common.observability import Metrics

__all__ = ["MitreMetrics"]


class MitreMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._s = service_name
        reg = base.registry
        self.mapped = Counter(
            "sm_mitre_mappings_total", "technique mappings written", ("service",), registry=reg,
        )
        self.unmapped = Counter(
            "sm_mitre_unmapped_total", "technique ids that were not in the catalog",
            ("service",), registry=reg,
        )
        self.detections = Counter(
            "sm_mitre_detections_total", "detections processed for mapping", ("service",), registry=reg,
        )
        self.map_requests = Counter(
            "sm_mitre_map_requests_total", "explicit /map API calls", ("service",), registry=reg,
        )
        self.catalog_techniques = Gauge(
            "sm_mitre_catalog_techniques", "techniques in the imported catalog",
            ("service",), registry=reg,
        )

    def detection(self, *, mapped: int, unmapped: int) -> None:
        self.detections.labels(self._s).inc()
        if mapped:
            self.mapped.labels(self._s).inc(mapped)
        if unmapped:
            self.unmapped.labels(self._s).inc(unmapped)

    def map_request(self, *, mapped: int, unmapped: int) -> None:
        self.map_requests.labels(self._s).inc()
        if mapped:
            self.mapped.labels(self._s).inc(mapped)
        if unmapped:
            self.unmapped.labels(self._s).inc(unmapped)
