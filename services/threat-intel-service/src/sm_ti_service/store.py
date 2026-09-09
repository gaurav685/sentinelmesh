"""IOC store of record (Postgres `threat_indicator`).

- **Never fabricates.** An indicator only exists because something put it here,
  and it carries a `Provenance` (`provider`, `source_kind`, `reference`,
  `retrieved_at`). A value that fails `normalize_indicator_value` is rejected.
- **Dedup** on `indicator_dedup_key` — global (`tenant_id IS NULL`) vs
  tenant-submitted (`(tenant_id, type, value)`). A repeat upsert extends the
  seen-window and refreshes confidence / reputation / expiry, it does not add a
  row.
- **Freshness** is derived on read (`freshness_for` against the configured TTL),
  never asserted by a caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from sm_common.clock import utcnow
from sm_common.db import Database, ThreatIndicatorRow
from sm_common.ids import uuid7
from sm_contracts import (
    EnrichmentMatch,
    IndicatorFreshness,
    IndicatorType,
    Provenance,
    ThreatIndicator,
    TiConfidence,
    TiSourceKind,
    TiUpdateAction,
    freshness_for,
    indicator_dedup_key,
    normalize_indicator_value,
)

from .reputation import reputation_score

__all__ = ["IndicatorInput", "IndicatorRepository"]


@dataclass
class IndicatorInput:
    type: IndicatorType
    value: str
    source: str
    source_kind: TiSourceKind
    confidence: TiConfidence
    tags: list[str] = field(default_factory=list)
    actor_id: str | None = None
    reference: str = ""
    tenant_id: UUID | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    expires_at: datetime | None = None


class IndicatorRepository:
    def __init__(self, db: Database, *, default_ttl_seconds: int) -> None:
        self._db = db
        self._ttl = timedelta(seconds=default_ttl_seconds)

    # ---- write --------------------------------------------------------
    async def upsert(self, inp: IndicatorInput) -> tuple[ThreatIndicator, TiUpdateAction]:
        value = normalize_indicator_value(inp.type, inp.value)  # raises ValueError -> caller rejects
        dedup = indicator_dedup_key(inp.type, value, inp.tenant_id)
        now = utcnow()
        first = inp.first_seen or now
        last = inp.last_seen or now
        expires = inp.expires_at or (last + self._ttl)
        reputation = reputation_score(inp.confidence, inp.tags)
        provenance: dict[str, Any] = {
            "provider": inp.source, "source_kind": inp.source_kind.value,
            "reference": inp.reference, "retrieved_at": now.isoformat(),
        }

        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(ThreatIndicatorRow).where(ThreatIndicatorRow.dedup_key == dedup)
                )
            ).scalars().first()
            if row is None:
                row = ThreatIndicatorRow(
                    id=uuid7(), tenant_id=inp.tenant_id, type=inp.type.value, value=value,
                    source=inp.source, confidence=inp.confidence.value, reputation=reputation,
                    first_seen=first, last_seen=last, expires_at=expires, tags=inp.tags,
                    actor_id=inp.actor_id, provenance=provenance, dedup_key=dedup,
                )
                s.add(row)
                action = TiUpdateAction.added
            else:
                row.first_seen = min(row.first_seen, first)
                row.last_seen = max(row.last_seen, last)
                row.confidence = inp.confidence.value
                row.reputation = reputation
                row.expires_at = expires
                row.tags = inp.tags
                row.source = inp.source
                row.actor_id = inp.actor_id
                row.provenance = provenance
                action = TiUpdateAction.updated
            await s.flush()
            dto = _to_dto(row, self._ttl, now)
        return dto, action

    # ---- read ------------------------------------------------------
    async def enrich(
        self, tenant_id: UUID, items: list[tuple[IndicatorType, str]]
    ) -> list[EnrichmentMatch]:
        now = utcnow()
        out: list[EnrichmentMatch] = []
        async with self._db.transaction() as s:
            for itype, raw in items:
                try:
                    value = normalize_indicator_value(itype, raw)
                except ValueError:
                    out.append(EnrichmentMatch(type=itype, value=raw, matched=False))
                    continue
                keys = [
                    indicator_dedup_key(itype, value, None),
                    indicator_dedup_key(itype, value, tenant_id),
                ]
                row = (
                    await s.execute(
                        select(ThreatIndicatorRow).where(ThreatIndicatorRow.dedup_key.in_(keys))
                    )
                ).scalars().first()
                if row is None:
                    out.append(EnrichmentMatch(type=itype, value=value, matched=False))
                    continue
                dto = _to_dto(row, self._ttl, now)
                fresh = dto.freshness is not IndicatorFreshness.expired
                out.append(EnrichmentMatch(
                    type=itype, value=value, matched=fresh,
                    indicator=dto if fresh else None, freshness=dto.freshness,
                ))
        return out

    async def list_indicators(
        self, tenant_id: UUID, *, indicator_type: IndicatorType | None = None, limit: int = 200
    ) -> list[ThreatIndicator]:
        now = utcnow()
        stmt = (
            select(ThreatIndicatorRow)
            .where(or_(ThreatIndicatorRow.tenant_id.is_(None), ThreatIndicatorRow.tenant_id == tenant_id))
            .order_by(ThreatIndicatorRow.last_seen.desc())
            .limit(max(1, min(limit, 1000)))
        )
        if indicator_type is not None:
            stmt = stmt.where(ThreatIndicatorRow.type == indicator_type.value)
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_to_dto(r, self._ttl, now) for r in rows]

    async def sweep_expired(self, since: datetime, now: datetime) -> list[ThreatIndicator]:
        """Indicators whose `expires_at` crossed into the past between `since` and
        `now` — emitted once as `ti.updates` action `expired`."""
        stmt = select(ThreatIndicatorRow).where(
            ThreatIndicatorRow.expires_at.is_not(None),
            ThreatIndicatorRow.expires_at > since,
            ThreatIndicatorRow.expires_at <= now,
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_to_dto(r, self._ttl, now) for r in rows]


def _provenance(data: dict[str, Any]) -> Provenance:
    return Provenance(
        provider=data["provider"],
        source_kind=TiSourceKind(data["source_kind"]),
        reference=data.get("reference", ""),
        retrieved_at=datetime.fromisoformat(data["retrieved_at"]),
    )


def _to_dto(row: ThreatIndicatorRow, ttl: timedelta, now: datetime) -> ThreatIndicator:
    return ThreatIndicator(
        id=row.id, created_at=row.created_at, updated_at=row.updated_at,
        type=IndicatorType(row.type), value=row.value, tenant_id=row.tenant_id,
        source=row.source, confidence=TiConfidence(row.confidence), reputation=row.reputation,
        first_seen=row.first_seen, last_seen=row.last_seen, expires_at=row.expires_at,
        freshness=freshness_for(row.last_seen, row.expires_at, ttl, now),
        tags=list(row.tags), actor_id=row.actor_id, provenance=_provenance(row.provenance),
    )
