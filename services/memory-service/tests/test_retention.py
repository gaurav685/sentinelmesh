from __future__ import annotations

from typing import Any

from sm_memory_service.metrics import MemoryMetrics
from sm_memory_service.retention import RetentionSweeper

from sm_common.observability import build_metrics


class FakeRepoOk:
    def __init__(self) -> None:
        self.calls = 0

    async def sweep_retention(self, **kw: Any) -> dict[str, int]:
        self.calls += 1
        return {"closed": 1, "dormant": 0, "deleted_campaigns": 0, "deleted_patterns": 2,
                "deleted_fingerprints": 0}


class FakeRepoFails:
    async def sweep_retention(self, **kw: Any) -> dict[str, int]:
        raise RuntimeError("db down")


def _sweeper(repo: Any) -> RetentionSweeper:
    metrics = MemoryMetrics(build_metrics("memory-service-test-retention"), "memory-service")
    return RetentionSweeper(
        repo=repo, metrics=metrics, interval_seconds=3600, dormant_after_days=14,
        close_after_days=60, retention_days=180,
    )


async def test_sweep_once_returns_the_repository_counts() -> None:
    repo = FakeRepoOk()
    sweeper = _sweeper(repo)
    counts = await sweeper.sweep_once()
    assert counts["deleted_patterns"] == 2
    assert repo.calls == 1


async def test_sweep_once_swallows_a_failure_and_returns_empty() -> None:
    sweeper = _sweeper(FakeRepoFails())
    counts = await sweeper.sweep_once()
    assert counts == {}
