"""Background expiry sweep.

Every `SM_TI_EXPIRY_SWEEP_SECONDS` it finds indicators whose `expires_at` crossed
into the past since the previous run and emits one `ti.updates` (`expired`) for
each. On a cold start it looks back one interval only, so a long-dead indicator
is not re-announced.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog

from sm_common.bus import EventBusProducer
from sm_common.clock import utcnow
from sm_contracts import TiUpdateAction

from .metrics import TiMetrics
from .publish import publish_update
from .store import IndicatorRepository

__all__ = ["ExpirySweeper"]

_log = structlog.get_logger("sm.ti_service.sweeper")


class ExpirySweeper:
    def __init__(
        self,
        *,
        repo: IndicatorRepository,
        producer: EventBusProducer,
        metrics: TiMetrics,
        interval_seconds: int,
    ) -> None:
        self._repo = repo
        self._producer = producer
        self._m = metrics
        self._interval = interval_seconds
        self._last = utcnow() - timedelta(seconds=interval_seconds)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                await self.sweep_once()

    async def sweep_once(self) -> int:
        now = utcnow()
        try:
            expired = await self._repo.sweep_expired(self._last, now)
        except Exception as exc:
            self._m.sweep_errors.labels("threat-intel-service").inc()
            _log.warning("expiry_sweep_failed", error=str(exc))
            return 0
        self._last = now
        for indicator in expired:
            try:
                await publish_update(self._producer, indicator, TiUpdateAction.expired)
                self._m.expired.labels("threat-intel-service").inc()
            except Exception as exc:
                self._m.sweep_errors.labels("threat-intel-service").inc()
                _log.warning("expiry_emit_failed", indicator_id=str(indicator.id), error=str(exc))
        return len(expired)

    def stop(self) -> None:
        self._stop.set()
