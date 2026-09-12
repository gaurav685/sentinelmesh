"""Persist a real `BenchmarkRun` to Postgres (`benchmark_experiment`, R24).

Plain `asyncpg`, not `sm-common` — `ml-training` stays an offline CLI tool,
not a service with a database dependency graph. `asyncpg` is already a
transitive dependency of every other service in this platform, so this adds
no new supply-chain surface, just a direct import.

The `benchmark_experiment` table's own `CHECK (executed IS TRUE)` constraint
is the actual enforcement point — this module does not additionally guard
against persisting an unexecuted run, since the schema already refuses one.
"""

from __future__ import annotations

import json
from uuid import uuid4

from .harness import BenchmarkRun

__all__ = ["save_benchmark_run"]

# Explicit ::jsonb casts: asyncpg binds a str parameter as `text`, and
# Postgres does not implicitly cast text -> jsonb for a bound parameter
# (only for a literal) — the same gotcha migration 0011 hit with
# `op.bulk_insert`, fixed the same way.
_INSERT_SQL = """
INSERT INTO benchmark_experiment (
    id, dataset_id, train_sha256, test_sha256, preprocessing_version,
    model_name, n_train, n_train_benign_used_for_fit, n_test,
    n_test_anomalous, params, seed, metrics, environment, executed,
    generated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13::jsonb,
    $14::jsonb, $15, $16
)
"""


async def save_benchmark_run(pg_dsn: str, run: BenchmarkRun) -> None:
    """Insert one real `BenchmarkRun` row. Raises if `run.executed` is not
    `True` (the table's `CHECK` constraint) or if the connection fails —
    never silently drops a write.

    `pg_dsn` accepts either the plain `postgresql://` form `asyncpg.connect`
    expects or `sm_common.config.AppSettings.pg_dsn`'s SQLAlchemy-style
    `postgresql+asyncpg://` form (the same property every other service
    already uses) — the `+asyncpg` driver marker is stripped either way, so
    a caller can pass either without an extra transform.
    """
    import asyncpg

    plain_dsn = pg_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(plain_dsn)
    try:
        await conn.execute(
            _INSERT_SQL,
            uuid4(),
            run.dataset_id,
            run.train_sha256,
            run.test_sha256,
            run.preprocessing_version,
            run.model_name,
            run.n_train,
            run.n_train_benign_used_for_fit,
            run.n_test,
            run.n_test_anomalous,
            json.dumps(run.params),
            run.seed,
            json.dumps(run.metrics),
            json.dumps(run.environment),
            run.executed,
            run.generated_at,
        )
    finally:
        await conn.close()
