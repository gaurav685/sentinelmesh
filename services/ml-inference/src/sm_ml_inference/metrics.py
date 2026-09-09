"""ml-inference Prometheus metrics (shared registry)."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from sm_common.observability import Metrics

__all__ = ["InferenceMetrics"]


class InferenceMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._service = service_name
        reg = base.registry
        self.requests = Counter(
            "sm_inference_requests_total",
            "inference requests by model and outcome",
            ("service", "model", "outcome"),
            registry=reg,
        )
        self.errors = Counter(
            "sm_inference_errors_total",
            "inference errors by model and type",
            ("service", "model", "error_type"),
            registry=reg,
        )
        self.duration = Histogram(
            "sm_inference_duration_seconds",
            "inference wall time by model",
            ("service", "model"),
            registry=reg,
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
        )
        self.model_loads = Counter(
            "sm_inference_model_loads_total",
            "model load attempts by model and outcome",
            ("service", "model", "outcome"),
            registry=reg,
        )

    def request(self, model: str, outcome: str) -> None:
        self.requests.labels(self._service, model, outcome).inc()

    def error(self, model: str, error_type: str) -> None:
        self.errors.labels(self._service, model, error_type).inc()

    def load(self, model: str, outcome: str) -> None:
        self.model_loads.labels(self._service, model, outcome).inc()
