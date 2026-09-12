"""SQLAlchemy model for real benchmark runs (Phase 15; R24).

Owner (write side): `ml-training`'s `sm_ml_training.benchmark.persist`, via
a plain `asyncpg` insert — `ml-training` stays an offline CLI tool, not a
service with `sm-common`'s dependency graph, so this row class is not used
to write. It exists so a read-only consumer (`api-gateway`'s
`BenchmarkRepository`, mirroring `SqlSocRepository`/`ContentRepository`'s
established precedent for reading a table its owning service exposes no
HTTP read API for) can query it through the normal `Database` session.

No `tenant_id`: this is research data, not tenant data (R24's own
security-boundary line). `params`/`metrics`/`environment` are JSONB for the
same reason `report`/`narrative`'s bodies are — a snapshot, not queried by
an individual metric's internal fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import uuid7
from .base import Base

__all__ = ["BenchmarkExperimentRow"]

_JSONB = postgresql.JSONB(astext_type=None)


class BenchmarkExperimentRow(Base):
    """Append-only, like `AuditLog` — a real run's record is never edited
    in place, so there is no `updated_at` (`TimestampMixin` is not used)."""

    __tablename__ = "benchmark_experiment"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    train_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    test_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    n_train: Mapped[int] = mapped_column(Integer(), nullable=False)
    n_train_benign_used_for_fit: Mapped[int] = mapped_column(Integer(), nullable=False)
    n_test: Mapped[int] = mapped_column(Integer(), nullable=False)
    n_test_anomalous: Mapped[int] = mapped_column(Integer(), nullable=False)
    #: `dict[str, Any]`, not a stricter type — see `NarrativeRow.body`'s
    #: docstring for why: non-authoritative JSON, trust-boundary-validated.
    params: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False)
    seed: Mapped[int] = mapped_column(Integer(), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False)
    environment: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False)
    executed: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    generated_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("executed IS TRUE", name="ck_benchmark_experiment_executed"),
        Index("ix_benchmark_experiment_dataset_generated", "dataset_id", "generated_at"),
    )
