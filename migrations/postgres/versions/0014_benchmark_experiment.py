"""Phase-15 schema: benchmark experiments (R24).

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-12

Notes
-----
- `benchmark_experiment` is research data, not tenant data (R24's own
  security-boundary line: "research datasets, no tenant data") — no
  `tenant_id`, unlike every tenant-scoped table so far. It is a global,
  append-only record of real, executed benchmark runs (`ml-training`'s
  `sm_ml_training.benchmark.harness.BenchmarkRun`, written directly via
  `sm_ml_training.benchmark.persist.save_benchmark_run` — a plain
  `asyncpg` insert, not a new HTTP service; `ml-training` remains an
  offline CLI tool, not a server).
- One row per real `run_benchmark(...)` call that opted to persist
  (`--save-to-db`); nothing populates this table from a fixture or a
  plumbing-check run.
- `params`/`metrics`/`environment` are JSONB, same rationale as
  `report`/`narrative`'s `body`: a benchmark run is a point-in-time
  snapshot, never queried by an individual metric's internal fields.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_experiment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("train_sha256", sa.String(length=64), nullable=False),
        sa.Column("test_sha256", sa.String(length=64), nullable=False),
        sa.Column("preprocessing_version", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("n_train", sa.Integer(), nullable=False),
        sa.Column("n_train_benign_used_for_fit", sa.Integer(), nullable=False),
        sa.Column("n_test", sa.Integer(), nullable=False),
        sa.Column("n_test_anomalous", sa.Integer(), nullable=False),
        sa.Column(
            "params", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "environment", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_benchmark_experiment"),
        sa.CheckConstraint("executed IS TRUE", name="ck_benchmark_experiment_executed"),
    )
    op.create_index(
        "ix_benchmark_experiment_dataset_generated",
        "benchmark_experiment", ["dataset_id", "generated_at"],
    )


def downgrade() -> None:
    op.drop_table("benchmark_experiment")
