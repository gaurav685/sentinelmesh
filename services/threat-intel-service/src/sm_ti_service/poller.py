"""Background provider poll.

Runs each enabled provider on a schedule, upserts what it returns, and emits
`ti.updates`. A provider outage (`ProviderResult.ok is False`) is logged and the
`ti_source` row is marked — the store keeps serving what it has (freshness ages
to `STALE`); nothing is fabricated. One poller instance per process (a single
poller per provider — `service-catalog.md`).
"""

from __future__ import annotations

import asyncio

import structlog

from sm_common.bus import EventBusProducer
from sm_common.clock import utcnow
from sm_common.db import Database, TiSourceRow
from sm_common.ids import uuid7
from sm_contracts import TiUpdateAction

from .metrics import TiMetrics
from .providers import ThreatIntelProvider
from .publish import publish_update
from .store import IndicatorInput, IndicatorRepository

__all__ = ["ProviderPoller"]

_log = structlog.get_logger("sm.ti_service.poller")


class ProviderPoller:
    def __init__(
        self,
        *,
        providers: list[ThreatIntelProvider],
        repo: IndicatorRepository,
        db: Database,
        producer: EventBusProducer,
        metrics: TiMetrics,
        interval_seconds: int,
        default_ttl_seconds: int,
    ) -> None:
        self._providers = providers
        self._repo = repo
        self._db = db
        self._producer = producer
        self._m = metrics
        self._interval = interval_seconds
        self._ttl = default_ttl_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        if not self._providers:
            return
        await self.poll_once()  # warm the cache at startup
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                await self.poll_once()

    async def poll_once(self) -> int:
        total = 0
        for provider in self._providers:
            result = await provider.fetch()
            status = "ok" if result.ok else f"degraded:{result.detail}"
            await self._record_source(provider, len(result.indicators), status)
            if not result.ok:
                _log.warning("provider_degraded", provider=provider.name, detail=result.detail)
                continue
            for raw in result.indicators:
                try:
                    indicator, action = await self._repo.upsert(IndicatorInput(
                        type=raw.type, value=raw.value, source=provider.name,
                        source_kind=provider.source_kind, confidence=raw.confidence,
                        tags=raw.tags, actor_id=raw.actor_id, reference=raw.reference,
                        tenant_id=None, expires_at=raw.expires_at,
                    ))
                except ValueError:
                    self._m.provider(provider.name, "malformed_rows")
                    continue
                self._m.upsert(action.value)
                total += 1
                if action in (TiUpdateAction.added, TiUpdateAction.updated):
                    try:
                        await publish_update(self._producer, indicator, action)
                    except Exception as exc:
                        _log.warning("ti_update_emit_failed", error=str(exc))
        return total

    async def _record_source(self, provider: ThreatIntelProvider, count: int, status: str) -> None:
        from sqlalchemy import select

        now = utcnow()
        async with self._db.transaction() as s:
            row = (
                await s.execute(select(TiSourceRow).where(TiSourceRow.name == provider.name))
            ).scalars().first()
            if row is None:
                s.add(TiSourceRow(
                    id=uuid7(), name=provider.name, kind=provider.source_kind.value, enabled=True,
                    ttl_seconds=self._ttl, last_poll_at=now, last_poll_status=status,
                    indicator_count=count,
                ))
            else:
                row.last_poll_at = now
                row.last_poll_status = status
                row.indicator_count = count

    def stop(self) -> None:
        self._stop.set()
