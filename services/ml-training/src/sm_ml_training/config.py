"""Training configuration — every knob that makes a run reproducible.

A run is fully described by a `TrainingConfig` plus the dataset it points at.
`config_hash` is a stable digest of the config, so two runs with the same config
and the same dataset produce byte-identical artifacts.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["DatasetKind", "ModelKind", "TrainingConfig"]


class ModelKind(StrEnum):
    structural = "structural"     # the always-available structural graph anomaly (no torch)
    graphsage = "graphsage"
    gat = "gat"


class DatasetKind(StrEnum):
    synthetic_fixture = "synthetic_fixture"   # a labelled toy graph — plumbing check, NOT a benchmark
    benchmark = "benchmark"                   # a registered dataset with an id + sha256


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    model_name: str = Field(min_length=1, max_length=64)
    model_kind: ModelKind = ModelKind.structural
    task: str = "node_anomaly"

    dataset_kind: DatasetKind = DatasetKind.synthetic_fixture
    dataset_path: str | None = None
    dataset_id: str | None = None

    seed: int = Field(default=1337, ge=0)
    val_fraction: float = Field(default=0.25, gt=0.0, lt=1.0)

    # GNN-only (ignored for `structural`).
    hidden_dim: int = Field(default=64, ge=4, le=1024)
    num_layers: int = Field(default=2, ge=1, le=8)
    epochs: int = Field(default=50, ge=1, le=10_000)
    learning_rate: float = Field(default=1e-3, gt=0.0, le=1.0)

    output_dir: str = "ml/artifacts/graph"

    def config_hash(self) -> str:
        payload: dict[str, Any] = self.model_dump(mode="json")
        payload.pop("output_dir", None)  # where it is written does not change what it is
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def model_version(self) -> str:
        return f"0.1.0+{self.config_hash()[:12]}"
