from __future__ import annotations

from typing import Any
from uuid import uuid4

from sm_ingestion_gateway.dedup import Dedup, DedupState


class _FakeRedis:
    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self._store: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if not self.healthy:
            raise ConnectionError("redis down")
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True


def _dedup(redis: Any) -> Dedup:
    return Dedup(redis, ttl_seconds=60)


async def test_first_call_is_fresh_then_duplicate() -> None:
    dedup = _dedup(_FakeRedis())
    sensor = uuid4()

    assert await dedup.check_and_mark(sensor, "evt-1") is DedupState.fresh
    assert await dedup.check_and_mark(sensor, "evt-1") is DedupState.duplicate
    assert await dedup.check_and_mark(sensor, "evt-2") is DedupState.fresh


async def test_redis_outage_reports_unavailable_not_duplicate() -> None:
    dedup = _dedup(_FakeRedis(healthy=False))
    assert await dedup.check_and_mark(uuid4(), "evt-1") is DedupState.unavailable
