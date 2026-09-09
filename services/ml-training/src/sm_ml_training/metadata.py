"""Model artifact metadata — what `metadata.json` records for every run."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["EvaluationReport", "ModelMetadata"]

_NOT_VERIFIED = "NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION"


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    dataset_id: str
    dataset_kind: str
    dataset_sha256: str
    n_val_samples: int
    n_val_nodes: int
    n_val_anomalous: int
    # Metrics computed on the val split of *this* dataset. For a synthetic
    # fixture these are a plumbing check, never a benchmark claim.
    val_metrics: dict[str, float] = Field(default_factory=dict)
    benchmark_verified: bool = False
    headline_metrics: str = _NOT_VERIFIED
    note: str = ""


class ModelMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_name: str
    model_version: str
    model_kind: str
    method: str
    task: str
    feature_schema_version: str
    seed: int
    config_hash: str
    dataset_id: str
    dataset_sha256: str
    git_commit: str | None = None
    created_at: datetime
    sm_ml_version: str
    torch_version: str | None = None
    torch_geometric_version: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    evaluation: EvaluationReport
