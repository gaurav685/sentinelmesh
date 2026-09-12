"""Benchmark & evaluation contracts (Phase 15; R24).

`BenchmarkExperiment` is the read shape of a real `benchmark_experiment` row
— every field here is a genuinely executed measurement (see `executed`,
always `True`; the table's own `CHECK` constraint enforces it, this is not
just a convention). No number is claimed here that was not produced by an
actual run of `sm_ml_training.benchmark.harness.run_benchmark` against a
real dataset file (Constitution §3, ADR-024).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc

__all__ = ["BenchmarkExperiment"]


class BenchmarkExperiment(SmBaseModel):
    id: UUID
    dataset_id: str = Field(min_length=1, max_length=64)
    train_sha256: str = Field(min_length=64, max_length=64)
    test_sha256: str = Field(min_length=64, max_length=64)
    preprocessing_version: str = Field(min_length=1, max_length=32)
    model_name: str = Field(min_length=1, max_length=64)
    n_train: int = Field(ge=0)
    n_train_benign_used_for_fit: int = Field(ge=0)
    n_test: int = Field(ge=0)
    n_test_anomalous: int = Field(ge=0)
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int
    metrics: dict[str, float] = Field(default_factory=dict)
    environment: dict[str, str | None] = Field(default_factory=dict)
    executed: bool
    generated_at: datetime
    created_at: datetime

    @field_validator("generated_at", "created_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)
