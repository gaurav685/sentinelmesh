"""Phase 6 Unit 4 — real PostgreSQL: the provider poller with the FIXTURE provider."""

from __future__ import annotations

from typing import Any

import pytest
from sm_ti_service.metrics import TiMetrics
from sm_ti_service.poller import ProviderPoller
from sm_ti_service.providers.fixture import FixtureProvider
from sm_ti_service.store import IndicatorRepository
from sqlalchemy import text

from sm_common.db import Database
from sm_common.observability import build_metrics

pytestmark = pytest.mark.integration


class _CaptureProducer:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, topic: str, *, key: str, value: bytes, headers: Any = None) -> None:
        self.sent.append(topic)


async def test_fixture_poll_upserts_and_emits_and_records_the_source(clean: Database) -> None:
    repo = IndicatorRepository(clean, default_ttl_seconds=3600)
    producer = _CaptureProducer()
    poller = ProviderPoller(
        providers=[FixtureProvider()], repo=repo, db=clean, producer=producer,  # type: ignore[arg-type]
        metrics=TiMetrics(build_metrics("threat-intel-service"), "threat-intel-service"),
        interval_seconds=3600, default_ttl_seconds=3600,
    )

    first = await poller.poll_once()
    assert first == 3  # the three fixture indicators
    assert producer.sent == ["ti.updates", "ti.updates", "ti.updates"]

    async with clean.transaction() as s:
        rows = (await s.execute(
            text("SELECT source, provenance->>'source_kind' FROM threat_indicator")
        )).all()
        src = (await s.execute(
            text("SELECT name, kind, last_poll_status, indicator_count FROM ti_source")
        )).one()
    assert {r[0] for r in rows} == {"fixture"}
    assert {r[1] for r in rows} == {"fixture"}  # labelled, never mistaken for a feed
    assert src == ("fixture", "fixture", "ok", 3)

    # a second identical poll is all updates, not new rows
    producer.sent.clear()
    await poller.poll_once()
    async with clean.transaction() as s:
        n = (await s.execute(text("SELECT count(*) FROM threat_indicator"))).scalar_one()
    assert n == 3
    assert len(producer.sent) == 3  # still emits an `updated` per indicator
