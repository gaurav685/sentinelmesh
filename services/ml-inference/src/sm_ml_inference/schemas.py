"""Inference API contract (DRAFT — Phase 5, service-local until it settles)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sm_contracts import AnomalyMethod, CanonicalKind

__all__ = [
    "GraphEdgeIn",
    "GraphInferRequest",
    "GraphInferResponse",
    "GraphModelInfo",
    "GraphNodeIn",
    "GraphNodeScoreOut",
    "InferRequest",
    "InferResponse",
    "ModelInfo",
    "ModelsResponse",
]

_CFG = ConfigDict(protected_namespaces=())


class InferRequest(BaseModel):
    model_config = _CFG

    kind: CanonicalKind
    feature_schema_version: str = Field(min_length=1, max_length=32)
    features: list[float] = Field(min_length=1, max_length=256)


class InferResponse(BaseModel):
    model_config = _CFG

    model: str
    method: AnomalyMethod
    model_version: str | None
    score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    threshold: float
    is_anomaly: bool
    contributing_features: list[str]


class ModelInfo(BaseModel):
    name: str
    version: str
    method: AnomalyMethod
    feature_schema_version: str
    task: str


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


# --------------------------------------------------------------------------- #
# graph inference (Phase 8)
# --------------------------------------------------------------------------- #
class GraphNodeIn(BaseModel):
    node_id: str = Field(min_length=1, max_length=256)
    node_type: str = Field(min_length=1, max_length=64)
    first_seen: float
    last_seen: float


class GraphEdgeIn(BaseModel):
    src_id: str = Field(min_length=1, max_length=256)
    dst_id: str = Field(min_length=1, max_length=256)
    edge_type: str = Field(min_length=1, max_length=64)
    observed_at: float


class GraphInferRequest(BaseModel):
    model_config = _CFG

    graph_feature_schema_version: str = Field(min_length=1, max_length=32)
    nodes: list[GraphNodeIn] = Field(min_length=1, max_length=20_000)
    edges: list[GraphEdgeIn] = Field(default_factory=list, max_length=100_000)


class GraphNodeScoreOut(BaseModel):
    node_id: str
    score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    is_anomaly: bool
    contributing_features: list[str]


class GraphInferResponse(BaseModel):
    model_config = _CFG

    model: str
    method: str
    model_version: str | None
    threshold: float
    feature_schema_version: str
    scores: list[GraphNodeScoreOut]


class GraphModelInfo(BaseModel):
    name: str
    version: str
    method: str
    task: str
    feature_schema_version: str
