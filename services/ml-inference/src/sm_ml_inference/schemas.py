"""Inference API contract (DRAFT — Phase 5, service-local until it settles)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sm_contracts import AnomalyMethod, CanonicalKind

__all__ = ["InferRequest", "InferResponse", "ModelInfo", "ModelsResponse"]

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
