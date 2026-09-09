"""Phase 6 Unit 3 — real PostgreSQL: the IOC store.

Upsert / dedup (global vs tenant), enrichment (hit / miss / expired), freshness,
the expiry sweep, and tenant isolation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_ti_service.store import IndicatorInput, IndicatorRepository
from sqlalchemy import text

from sm_common.db import Database
from sm_contracts import IndicatorFreshness, IndicatorType, TiConfidence, TiSourceKind, TiUpdateAction

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)


async def _tenant(db: Database) -> uuid.UUID:
    tid = uuid.uuid4()
    async with db.transaction() as s:
        await s.execute(
            text("INSERT INTO tenant (id, slug, name, status) VALUES (:id, :slug, 'T', 'active')"),
            {"id": tid, "slug": f"t-{tid.hex[:12]}"},
        )
    return tid


def _repo(db: Database) -> IndicatorRepository:
    return IndicatorRepository(db, default_ttl_seconds=3600)


def _input(**over: object) -> IndicatorInput:
    base: dict[str, object] = dict(
        type=IndicatorType.ipv4, value="203.0.113.7", source="fixture:demo",
        source_kind=TiSourceKind.fixture, confidence=TiConfidence.high, tags=["c2"],
    )
    base.update(over)
    return IndicatorInput(**base)  # type: ignore[arg-type]


async def test_upsert_adds_then_updates_the_same_row(clean: Database) -> None:
    repo = _repo(clean)
    ind1, a1 = await repo.upsert(_input(confidence=TiConfidence.low))
    assert a1 is TiUpdateAction.added

    ind2, a2 = await repo.upsert(_input(confidence=TiConfidence.high))
    assert a2 is TiUpdateAction.updated
    assert ind2.id == ind1.id
    assert ind2.confidence is TiConfidence.high
    assert ind2.reputation > ind1.reputation

    async with clean.transaction() as s:
        n = (await s.execute(text("SELECT count(*) FROM threat_indicator"))).scalar_one()
    assert n == 1


async def test_global_and_tenant_indicators_are_separate_rows(clean: Database) -> None:
    repo = _repo(clean)
    t = await _tenant(clean)
    await repo.upsert(_input())                       # global
    await repo.upsert(_input(tenant_id=t))            # tenant-submitted, same value
    async with clean.transaction() as s:
        n = (await s.execute(text("SELECT count(*) FROM threat_indicator"))).scalar_one()
    assert n == 2


async def test_enrich_hit_miss_and_expired(clean: Database) -> None:
    repo = _repo(clean)
    t = await _tenant(clean)
    await repo.upsert(_input(value="198.51.100.9"))
    await repo.upsert(_input(value="198.51.100.10", expires_at=_NOW - timedelta(minutes=1)))

    results = await repo.enrich(t, [
        (IndicatorType.ipv4, "198.51.100.9"),
        (IndicatorType.ipv4, "198.51.100.10"),
        (IndicatorType.ipv4, "8.8.8.8"),
        (IndicatorType.ipv4, "not-an-ip"),
    ])
    assert results[0].matched is True and results[0].indicator is not None
    assert results[1].matched is False and results[1].freshness is IndicatorFreshness.expired
    assert results[2].matched is False and results[2].freshness is None
    assert results[3].matched is False  # malformed -> not a match, not an error


async def test_list_is_global_plus_this_tenant(clean: Database) -> None:
    repo = _repo(clean)
    t1, t2 = await _tenant(clean), await _tenant(clean)
    await repo.upsert(_input(value="192.0.2.1"))                 # global
    await repo.upsert(_input(value="192.0.2.2", tenant_id=t1))   # t1
    await repo.upsert(_input(value="192.0.2.3", tenant_id=t2))   # t2

    seen = {i.value for i in await repo.list_indicators(t1)}
    assert seen == {"192.0.2.1", "192.0.2.2"}


async def test_sweep_returns_indicators_that_crossed_into_expired(clean: Database) -> None:
    repo = _repo(clean)
    old = datetime.now(UTC) - timedelta(hours=2)
    await repo.upsert(_input(value="203.0.113.50", expires_at=datetime.now(UTC) - timedelta(minutes=30)))
    await repo.upsert(_input(value="203.0.113.51", expires_at=datetime.now(UTC) + timedelta(hours=1)))

    expired = await repo.sweep_expired(old, datetime.now(UTC))
    assert [i.value for i in expired] == ["203.0.113.50"]
