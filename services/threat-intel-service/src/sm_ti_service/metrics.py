"""threat-intel-service Prometheus metrics (shared registry)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from sm_common.observability import Metrics

__all__ = ["TiMetrics"]


class TiMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._s = service_name
        reg = base.registry
        self.upserts = Counter(
            "sm_ti_indicator_upserts_total", "indicator upserts by action",
            ("service", "action"), registry=reg,
        )
        self.enrich_lookups = Counter(
            "sm_ti_enrich_lookups_total", "enrichment lookups by outcome",
            ("service", "outcome"), registry=reg,
        )
        self.expired = Counter(
            "sm_ti_expired_total", "indicators observed crossing into expired",
            ("service",), registry=reg,
        )
        self.sweep_errors = Counter(
            "sm_ti_sweep_errors_total", "expiry-sweep failures", ("service",), registry=reg,
        )
        self.provider_calls = Counter(
            "sm_ti_provider_calls_total", "provider adapter calls by provider and outcome",
            ("service", "provider", "outcome"), registry=reg,
        )
        self.provider_latency = Histogram(
            "sm_ti_provider_latency_seconds", "provider adapter latency by provider",
            ("service", "provider"), registry=reg,
        )
        self.indicators = Gauge(
            "sm_ti_indicators", "indicators in the store by freshness",
            ("service", "freshness"), registry=reg,
        )

    def upsert(self, action: str) -> None:
        self.upserts.labels(self._s, action).inc()

    def enrich(self, outcome: str) -> None:
        self.enrich_lookups.labels(self._s, outcome).inc()

    def provider(self, provider: str, outcome: str) -> None:
        self.provider_calls.labels(self._s, provider, outcome).inc()
