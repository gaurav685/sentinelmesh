"""simulation-service Prometheus metrics."""

from __future__ import annotations

from prometheus_client import Counter

from sm_common.observability import Metrics

__all__ = ["SimulationMetrics"]


class SimulationMetrics:
    def __init__(self, base: Metrics, service: str) -> None:
        self._service = service
        self.scenario_runs = Counter(
            "sm_sim_scenario_runs_total",
            "Scenario runs by kind and whether they fed the pipeline.",
            ["service", "kind", "fed_pipeline"],
            registry=base.registry,
        )
        self.scenario_refused = Counter(
            "sm_sim_scenario_refused_total",
            "Scenario runs refused for isolation violations.",
            ["service"],
            registry=base.registry,
        )
        self.decoy_events = Counter(
            "sm_sim_decoy_events_total",
            "Decoy lifecycle and interaction events, by kind.",
            ["service", "event"],
            registry=base.registry,
        )

    def run(self, *, kind: str, fed_pipeline: bool) -> None:
        self.scenario_runs.labels(self._service, kind, "true" if fed_pipeline else "false").inc()

    def refused(self) -> None:
        self.scenario_refused.labels(self._service).inc()

    def decoy(self, event: str) -> None:
        self.decoy_events.labels(self._service, event).inc()
