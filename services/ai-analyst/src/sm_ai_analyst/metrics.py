"""ai-analyst Prometheus metrics."""

from __future__ import annotations

from prometheus_client import Counter

from sm_common.observability import Metrics

__all__ = ["AnalystMetrics"]


class AnalystMetrics:
    def __init__(self, base: Metrics, service: str) -> None:
        self._service = service
        self.explanations = Counter(
            "sm_analyst_explanations_total",
            "Explanations produced, by task / degraded / confidence.",
            ["service", "task", "degraded", "confidence"],
            registry=base.registry,
        )
        self.injection_flagged = Counter(
            "sm_analyst_evidence_injection_flagged_total",
            "Explain requests whose gathered evidence contained an injection pattern.",
            ["service"],
            registry=base.registry,
        )

    def observed(self, *, task: str, degraded: bool, confidence: str) -> None:
        self.explanations.labels(
            self._service, task, "true" if degraded else "false", confidence
        ).inc()

    def flagged(self) -> None:
        self.injection_flagged.labels(self._service).inc()
