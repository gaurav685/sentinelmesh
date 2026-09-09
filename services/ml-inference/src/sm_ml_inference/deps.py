"""Dependency wiring for ml-inference.

`ModelHost` owns the registry and a per-model cache. Models are loaded lazily on
first use and kept until `reload()` (hot-reload on a new registered version). A
model that cannot be loaded raises `ModelUnavailable` every time — the caller
degrades, ml-inference never fabricates a score.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from sm_common.config import AppSettings
from sm_common.errors import Unauthenticated
from sm_common.observability import Metrics
from sm_common.security import InternalPrincipal, verify_internal_token
from sm_ml import AnomalyModel, ModelRegistry
from sm_ml.graph import GraphModelRegistry, GraphModelUnavailable, StructuralGraphAnomaly
from sm_ml.graph.models.base import GraphAnomalyModel
from sm_ml.graph.registry import GraphModelRef
from sm_ml.models import ModelUnavailable
from sm_ml.registry import ModelRef

from .metrics import InferenceMetrics
from .version import SERVICE_NAME

__all__ = [
    "GraphModelHost",
    "ModelHost",
    "Services",
    "get_graph_host",
    "get_host",
    "get_principal",
    "get_services",
]

# Names that resolve to the always-available structural detector (no artifact).
_STRUCTURAL_NAMES = frozenset({"structural", "structural_zscore", "graph_anomaly"})


class ModelHost:
    def __init__(self, registry: ModelRegistry, metrics: InferenceMetrics) -> None:
        self._registry = registry
        self._metrics = metrics
        self._cache: dict[str, AnomalyModel] = {}

    @property
    def metrics(self) -> InferenceMetrics:
        return self._metrics

    def catalog(self) -> list[ModelRef]:
        return self._registry.available()

    def loaded(self) -> list[str]:
        return sorted(self._cache)

    def get(self, name: str) -> AnomalyModel:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        try:
            model = self._registry.load(name)
        except ModelUnavailable:
            self._metrics.load(name, "unavailable")
            raise
        self._metrics.load(name, "ok")
        self._cache[name] = model
        return model

    def reload(self) -> None:
        self._cache.clear()


class GraphModelHost:
    """Serves the Phase-8 graph models. The structural detector is always
    available (fixed code, no artifact); a GNN name goes through the registry and
    raises `GraphModelUnavailable` when its artifact or `torch` is missing — the
    caller degrades to the structural path."""

    def __init__(self, registry: GraphModelRegistry, metrics: InferenceMetrics) -> None:
        self._registry = registry
        self._metrics = metrics
        self._cache: dict[str, GraphAnomalyModel] = {}

    @property
    def metrics(self) -> InferenceMetrics:
        return self._metrics

    def catalog(self) -> list[GraphModelRef]:
        return self._registry.available()

    def loaded(self) -> list[str]:
        return sorted(self._cache)

    def get(self, name: str) -> GraphAnomalyModel:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        if name in _STRUCTURAL_NAMES and not any(r.name == name for r in self._registry.available()):
            model: GraphAnomalyModel = StructuralGraphAnomaly()
        else:
            try:
                model = self._registry.load(name)
            except GraphModelUnavailable:
                self._metrics.load(f"graph:{name}", "unavailable")
                raise
        self._metrics.load(f"graph:{name}", "ok")
        self._cache[name] = model
        return model

    def reload(self) -> None:
        self._cache.clear()


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    inference_metrics: InferenceMetrics
    host: ModelHost
    graph_host: GraphModelHost


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_host(services: Services = Depends(get_services)) -> ModelHost:
    return services.host


def get_graph_host(services: Services = Depends(get_services)) -> GraphModelHost:
    return services.graph_host


def get_principal(
    request: Request, services: Services = Depends(get_services)
) -> InternalPrincipal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        services.metrics.authn_failures.labels(SERVICE_NAME, "no_bearer_token").inc()
        raise Unauthenticated()
    try:
        return verify_internal_token(
            token,
            signing_keys=[services.settings.internal_jwt_signing_key.get_secret_value()],
            audience=SERVICE_NAME,
            leeway_seconds=services.settings.jwt_leeway_seconds,
        )
    except Unauthenticated:
        services.metrics.authn_failures.labels(SERVICE_NAME, "internal_token_invalid").inc()
        raise
