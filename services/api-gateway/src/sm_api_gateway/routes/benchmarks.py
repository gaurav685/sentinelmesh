"""Benchmark & evaluation results BFF (Phase 15, Unit 4; R24).

Read-only, direct-SQL against `benchmark_experiment` — `ml-training` has no
HTTP read API of its own (it is an offline CLI tool), so this repository
reads the table directly, the same established pattern `SqlSocRepository`/
`ContentRepository` use for `detection`/`threat_score`. Gated on `ops:read`
(the existing tier, not a new permission code) since a benchmark run is
platform research data, never tenant data.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sm_common.errors import NotFound
from sm_contracts import BenchmarkExperiment, PermissionCode

from ..deps import get_benchmark_repository, require_permission
from ..repositories.protocols import BenchmarkRepository
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/soc", tags=["benchmarks"])

_read = require_permission(PermissionCode.ops_read)


@router.get("/benchmarks", response_model=list[BenchmarkExperiment])
async def list_benchmarks(
    dataset_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    _principal: Principal = Depends(_read),
    repo: BenchmarkRepository = Depends(get_benchmark_repository),
) -> list[BenchmarkExperiment]:
    return await repo.list_recent(dataset_id=dataset_id, limit=limit)


@router.get("/benchmarks/{experiment_id}", response_model=BenchmarkExperiment)
async def get_benchmark(
    experiment_id: UUID,
    _principal: Principal = Depends(_read),
    repo: BenchmarkRepository = Depends(get_benchmark_repository),
) -> BenchmarkExperiment:
    result = await repo.get(experiment_id)
    if result is None:
        raise NotFound("benchmark experiment not found")
    return result
