"""Read-only access to real benchmark runs (Phase 15; R24).

`ml-training` exposes no HTTP read API of its own — it is an offline CLI
tool, not a service (`sm_ml_training.benchmark.persist.save_benchmark_run`
is the only writer, a plain `asyncpg` insert). `SqlSocRepository` and
`ContentRepository` already established the precedent for a BFF reading
another domain's table directly when its owning component has no read API;
this mirrors that. No `tenant_id` anywhere — a benchmark run is platform
research data (R24's own security-boundary line), never tenant data.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_common.db import BenchmarkExperimentRow
from sm_contracts import BenchmarkExperiment

__all__ = ["SqlBenchmarkRepository"]

_MAX_LIMIT = 200


def _out(row: BenchmarkExperimentRow) -> BenchmarkExperiment:
    return BenchmarkExperiment(
        id=row.id, dataset_id=row.dataset_id, train_sha256=row.train_sha256,
        test_sha256=row.test_sha256, preprocessing_version=row.preprocessing_version,
        model_name=row.model_name, n_train=row.n_train,
        n_train_benign_used_for_fit=row.n_train_benign_used_for_fit,
        n_test=row.n_test, n_test_anomalous=row.n_test_anomalous,
        params=dict(row.params), seed=row.seed, metrics=dict(row.metrics),
        environment=dict(row.environment), executed=row.executed,
        generated_at=row.generated_at, created_at=row.created_at,
    )


class SqlBenchmarkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_recent(
        self, *, dataset_id: str | None = None, limit: int = 50,
    ) -> list[BenchmarkExperiment]:
        bounded = min(limit, _MAX_LIMIT)
        stmt = select(BenchmarkExperimentRow).order_by(BenchmarkExperimentRow.generated_at.desc())
        if dataset_id is not None:
            stmt = stmt.where(BenchmarkExperimentRow.dataset_id == dataset_id)
        stmt = stmt.limit(bounded)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_out(r) for r in rows]

    async def get(self, experiment_id: UUID) -> BenchmarkExperiment | None:
        row = await self._session.get(BenchmarkExperimentRow, experiment_id)
        return _out(row) if row is not None else None
