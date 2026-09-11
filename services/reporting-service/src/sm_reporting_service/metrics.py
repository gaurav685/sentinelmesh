"""reporting-service Prometheus metrics (service-catalog observability:
report volume by kind, generation latency, PARTIAL/FAILED counts)."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from sm_common.observability import Metrics

__all__ = ["ReportMetrics"]


class ReportMetrics:
    def __init__(self, base: Metrics, service: str) -> None:
        self._service = service
        self.generated = Counter(
            "sm_reports_generated_total", "Reports generated, by kind and final status.",
            ["service", "kind", "status"], registry=base.registry,
        )
        self.generation_seconds = Histogram(
            "sm_report_generation_seconds", "Wall-clock time to assemble + render + upload a report.",
            ["service", "kind"], registry=base.registry,
        )
        self.content_dependency_missing = Counter(
            "sm_report_content_dependency_missing_total",
            "A content dependency was unreachable while assembling a report.",
            ["service", "dependency"], registry=base.registry,
        )

    def report_generated(self, *, kind: str, status: str) -> None:
        self.generated.labels(self._service, kind, status).inc()

    def observe_generation_seconds(self, *, kind: str, seconds: float) -> None:
        self.generation_seconds.labels(self._service, kind).observe(seconds)

    def content_dependency_unavailable(self, dependency: str) -> None:
        self.content_dependency_missing.labels(self._service, dependency).inc()
