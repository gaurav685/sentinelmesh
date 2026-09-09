"""Typed inference endpoints (ADR-013).

A model that is not registered / not loadable / whose serving deps are missing
→ HTTP 503 `dependency_unavailable` with `MODEL_UNAVAILABLE` in the message and
a `model` detail. `detection-engine` treats that as `scoring_status = DEGRADED`
and falls back to the statistical detector — it is never a 500 and never a
fabricated score.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from sm_common.errors import DependencyUnavailable, ValidationFailed
from sm_common.security import InternalPrincipal
from sm_contracts import ErrorDetail
from sm_ml import FEATURE_SCHEMA_VERSION, schema_for
from sm_ml.graph import GRAPH_FEATURE_SCHEMA_VERSION, GraphEdge, GraphNode, build_graph_sample
from sm_ml.graph.models.base import GraphModelError, GraphModelUnavailable
from sm_ml.models import ModelError, ModelUnavailable

from ..deps import GraphModelHost, ModelHost, get_graph_host, get_host, get_principal
from ..schemas import (
    GraphInferRequest,
    GraphInferResponse,
    GraphModelInfo,
    GraphNodeScoreOut,
    InferRequest,
    InferResponse,
    ModelInfo,
    ModelsResponse,
)
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=API_PREFIX, tags=["inference"])


def _unavailable(model: str, reason: str) -> DependencyUnavailable:
    return DependencyUnavailable(
        f"MODEL_UNAVAILABLE: {model}",
        details=[ErrorDetail(field="model", issue=reason)],
    )


@router.get("/models", response_model=ModelsResponse)
async def models(
    host: ModelHost = Depends(get_host),
    _principal: InternalPrincipal = Depends(get_principal),
) -> ModelsResponse:
    return ModelsResponse(
        models=[
            ModelInfo(
                name=r.name, version=r.version, method=r.method,
                feature_schema_version=r.feature_schema_version, task=r.task,
            )
            for r in host.catalog()
        ]
    )


@router.post("/infer/{model}", response_model=InferResponse)
async def infer(
    model: str,
    req: InferRequest,
    host: ModelHost = Depends(get_host),
    _principal: InternalPrincipal = Depends(get_principal),
) -> InferResponse:
    if req.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ValidationFailed(
            f"feature_schema_version {req.feature_schema_version!r} != "
            f"server {FEATURE_SCHEMA_VERSION!r}"
        )
    expected = len(schema_for(req.kind).names)
    if len(req.features) != expected:
        raise ValidationFailed(
            f"expected {expected} features for kind {req.kind.value}, got {len(req.features)}"
        )

    try:
        estimator = host.get(model)
    except ModelUnavailable as exc:
        host.metrics.request(model, "unavailable")
        raise _unavailable(model, str(exc)) from exc

    start = time.perf_counter()
    try:
        score = estimator.score(req.features)
    except ModelError as exc:
        host.metrics.error(model, type(exc).__name__)
        host.metrics.request(model, "error")
        raise _unavailable(model, f"inference failed: {exc}") from exc
    host.metrics.duration.labels("ml-inference", model).observe(time.perf_counter() - start)
    host.metrics.request(model, "ok")

    return InferResponse(
        model=model,
        method=score.method,
        model_version=score.model_version,
        score=score.score,
        normalized_score=score.normalized_score,
        threshold=score.threshold,
        is_anomaly=score.is_anomaly,
        contributing_features=score.contributing_features,
    )


# --------------------------------------------------------------------------- #
# graph inference (Phase 8)
# --------------------------------------------------------------------------- #
@router.get("/graph/models", response_model=list[GraphModelInfo])
async def graph_models(
    graph_host: GraphModelHost = Depends(get_graph_host),
    _principal: InternalPrincipal = Depends(get_principal),
) -> list[GraphModelInfo]:
    registered = [
        GraphModelInfo(
            name=r.name, version=r.version, method=r.method, task=r.task,
            feature_schema_version=r.feature_schema_version,
        )
        for r in graph_host.catalog()
    ]
    if not any(r.name == "structural" for r in registered):
        registered.append(GraphModelInfo(
            name="structural", version="builtin", method="structural_zscore",
            task="node_anomaly", feature_schema_version=GRAPH_FEATURE_SCHEMA_VERSION,
        ))
    return registered


@router.post("/infer/graph/{model}", response_model=GraphInferResponse)
async def infer_graph(
    model: str,
    req: GraphInferRequest,
    graph_host: GraphModelHost = Depends(get_graph_host),
    _principal: InternalPrincipal = Depends(get_principal),
) -> GraphInferResponse:
    if req.graph_feature_schema_version != GRAPH_FEATURE_SCHEMA_VERSION:
        raise ValidationFailed(
            f"graph_feature_schema_version {req.graph_feature_schema_version!r} != "
            f"server {GRAPH_FEATURE_SCHEMA_VERSION!r}"
        )
    try:
        sample = build_graph_sample(
            [GraphNode(n.node_id, n.node_type, n.first_seen, n.last_seen) for n in req.nodes],
            [GraphEdge(e.src_id, e.dst_id, e.edge_type, e.observed_at) for e in req.edges],
        )
    except ValueError as exc:
        raise ValidationFailed(f"invalid graph sample: {exc}") from exc

    try:
        estimator = graph_host.get(model)
    except GraphModelUnavailable as exc:
        graph_host.metrics.request(f"graph:{model}", "unavailable")
        raise _unavailable(model, str(exc)) from exc

    start = time.perf_counter()
    try:
        result = estimator.score_nodes(sample)
    except GraphModelError as exc:
        graph_host.metrics.error(f"graph:{model}", type(exc).__name__)
        graph_host.metrics.request(f"graph:{model}", "error")
        raise _unavailable(model, f"inference failed: {exc}") from exc
    graph_host.metrics.duration.labels("ml-inference", f"graph:{model}").observe(
        time.perf_counter() - start
    )
    graph_host.metrics.request(f"graph:{model}", "ok")

    return GraphInferResponse(
        model=model, method=result.method, model_version=result.model_version,
        threshold=result.threshold, feature_schema_version=result.feature_schema_version,
        scores=[
            GraphNodeScoreOut(
                node_id=s.node_id, score=s.score, normalized_score=s.normalized_score,
                is_anomaly=s.is_anomaly, contributing_features=s.contributing_features,
            )
            for s in result.scores
        ],
    )
