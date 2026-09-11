"""memory-service Prometheus metrics."""

from __future__ import annotations

from prometheus_client import Counter

from sm_common.observability import Metrics

__all__ = ["MemoryMetrics"]


class MemoryMetrics:
    def __init__(self, base: Metrics, service: str) -> None:
        self._service = service
        self.chains_ingested = Counter(
            "sm_memory_chains_ingested_total", "Attack-chain updates ingested into threat memory.",
            ["service"], registry=base.registry,
        )
        self.chains_skipped = Counter(
            "sm_memory_chains_skipped_total",
            "Attack-chain updates skipped (not found, or no techniques to learn from).",
            ["service"], registry=base.registry,
        )
        self.campaign_updates_emitted = Counter(
            "sm_memory_campaign_updates_emitted_total", "campaign.updates events produced.",
            ["service"], registry=base.registry,
        )
        self.similarity_fallback = Counter(
            "sm_memory_similarity_fallback_total",
            "Similarity queries that fell back to the exact-match Python scan.",
            ["service"], registry=base.registry,
        )
        self.retention_sweep_errors = Counter(
            "sm_memory_retention_sweep_errors_total", "Retention sweep failures.",
            ["service"], registry=base.registry,
        )

    def chain_ingested(self) -> None:
        self.chains_ingested.labels(self._service).inc()

    def chain_skipped(self) -> None:
        self.chains_skipped.labels(self._service).inc()

    def campaign_update_emitted(self) -> None:
        self.campaign_updates_emitted.labels(self._service).inc()

    def similarity_fell_back(self) -> None:
        self.similarity_fallback.labels(self._service).inc()

    def retention_sweep_error(self) -> None:
        self.retention_sweep_errors.labels(self._service).inc()
