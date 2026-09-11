"""Background retention sweep — the deletion lifecycle for threat memory.

Every `SM_MEMORY_RETENTION_SWEEP_SECONDS` it ages campaigns
`active -> dormant -> closed` on inactivity and deletes patterns,
fingerprints, and long-closed campaigns whose `last_seen` crossed the hard
retention window. A sweep failure is logged and counted, never raised into
the request path — retention is best-effort background hygiene, not
something a caller waits on.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog

from .metrics import MemoryMetrics
from .repository import MemoryRepository

__all__ = ["RetentionSweeper"]

_log = structlog.get_logger("sm.memory_service.retention")


class RetentionSweeper:
    def __init__(
        self, *, repo: MemoryRepository, metrics: MemoryMetrics, interval_seconds: int,
        dormant_after_days: int, close_after_days: int, retention_days: int,
    ) -> None:
        self._repo = repo
        self._m = metrics
        self._interval = interval_seconds
        self._dormant_after = timedelta(days=dormant_after_days)
        self._close_after = timedelta(days=close_after_days)
        self._retention = timedelta(days=retention_days)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                await self.sweep_once()

    async def sweep_once(self) -> dict[str, int]:
        try:
            counts = await self._repo.sweep_retention(
                dormant_after=self._dormant_after, close_after=self._close_after,
                delete_after=self._retention,
            )
        except Exception as exc:
            self._m.retention_sweep_error()
            _log.warning("retention_sweep_failed", error=str(exc))
            return {}
        _log.info("retention_swept", **counts)
        return counts

    def stop(self) -> None:
        self._stop.set()
