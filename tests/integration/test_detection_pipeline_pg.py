"""Phase 5 Unit 5 — real PostgreSQL: the detection pipeline persists correctly.

`events.canonical` (an auth-failure burst) -> `detection-engine` engine ->
`detection` / `anomaly` / `security_alert` rows with grounded evidence, tenant
isolation, and dedup on reprocess. `ml-inference` is stubbed absent, so this also
exercises the ADR-013 degraded path.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_detection_engine.engine import DetectionEngine
from sm_detection_engine.metrics import DetectionMetrics
from sm_detection_engine.repository import DetectionRepository
from sqlalchemy import func, select, text

from sm_common.db import Database, Detection, SecurityAlert
from sm_common.observability import build_metrics
from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EntityRef,
    EventEnvelope,
    EventSource,
    EventType,
    SourceType,
    make_partition_key,
)

from .conftest import integration_settings

pytestmark = pytest.mark.integration


class _NoModel:
    async def score(self, *_a: object, **_kw: object) -> None:
        return None


class _CaptureProducer:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, topic: str, *, key: str, value: bytes, headers: object = None) -> None:
        if topic == "detections":
            self.sent.append(json.loads(value))


def _auth_failure(tenant: uuid.UUID, principal: str, *, at: datetime) -> EventEnvelope[CanonicalEventPayload]:
    actor = EntityRef(kind="identity", value=principal)
    target = EntityRef(kind="host", value="dc01")
    raw = uuid.uuid4()
    payload = CanonicalEventPayload(
        kind=CanonicalKind.auth, occurred_at=at, action="authentication_failed",
        outcome="failure", actor=actor, target=target, entities=[actor, target],
        raw_event_id=raw, raw_event_type=EventType.telemetry_auth_event,
        attributes={"auth_type": "password", "failure_reason": "bad_password"},
    )
    return EventEnvelope[CanonicalEventPayload](
        event_id=uuid.uuid4(), event_type=EventType.event_canonical, event_version=1,
        occurred_at=at, ingested_at=datetime.now(UTC), producer="normalization-engine@0.1.0",
        tenant_id=tenant, source=EventSource(type=SourceType.sensor, sensor_id=uuid.uuid4()),
        correlation_id=uuid.uuid4(), partition_key=make_partition_key(tenant, principal),
        payload=payload, metadata={"raw_event_id": str(raw)},
    )


def _record(env: EventEnvelope[CanonicalEventPayload]) -> object:
    from aiokafka.structs import ConsumerRecord

    v = env.model_dump_json().encode()
    return ConsumerRecord(
        topic="events.canonical", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=v, checksum=None, serialized_key_size=0,
        serialized_value_size=len(v), headers=(),
    )


@pytest.fixture
def engine(clean: Database) -> tuple[DetectionEngine, _CaptureProducer]:
    settings = integration_settings(detection_min_samples=10, detection_window_size=64)
    base = build_metrics("detection-engine")
    producer = _CaptureProducer()
    eng = DetectionEngine(
        settings=settings, repository=DetectionRepository(clean), producer=producer,  # type: ignore[arg-type]
        inference=_NoModel(), metrics=DetectionMetrics(base, "detection-engine"),  # type: ignore[arg-type]
    )
    return eng, producer


async def _seed_tenant(db: Database, tid: uuid.UUID) -> None:
    async with db.transaction() as s:
        await s.execute(
            text("INSERT INTO tenant (id, slug, name, status) VALUES (:id, :slug, 'T', 'active')"),
            {"id": tid, "slug": f"t-{tid.hex[:12]}"},
        )


async def test_auth_burst_persists_a_detection_with_evidence(
    engine: tuple[DetectionEngine, _CaptureProducer], clean: Database
) -> None:
    eng, producer = engine
    tenant = uuid.uuid4()
    await _seed_tenant(clean, tenant)

    base = datetime.now(UTC) - timedelta(minutes=1)
    for i in range(6):
        await eng.handle(_record(_auth_failure(tenant, "svc-backup", at=base + timedelta(seconds=i))))

    async with clean.transaction() as s:
        dets = (await s.execute(select(Detection).where(Detection.tenant_id == tenant))).scalars().all()
    assert len(dets) == 1
    det = dets[0]
    assert det.rule_id == "rule.auth.failed_burst"
    assert "T1110" in det.technique_ids
    kinds = {e["kind"] for e in det.evidence}
    assert "rule_match" in kinds and "event" in kinds
    assert all("provenance" in e for e in det.evidence)

    assert producer.sent and producer.sent[-1]["payload"]["detection_id"] == str(det.id)


async def test_high_severity_burst_opens_exactly_one_alert(
    engine: tuple[DetectionEngine, _CaptureProducer], clean: Database
) -> None:
    eng, _ = engine
    tenant = uuid.uuid4()
    await _seed_tenant(clean, tenant)
    base = datetime.now(UTC) - timedelta(minutes=1)
    for i in range(18):  # >= 15 failures escalates to high
        await eng.handle(_record(_auth_failure(tenant, "root", at=base + timedelta(seconds=i))))

    async with clean.transaction() as s:
        alerts = (await s.execute(select(SecurityAlert).where(SecurityAlert.tenant_id == tenant))).scalars().all()
        det_count = (await s.execute(
            select(func.count()).select_from(Detection).where(Detection.tenant_id == tenant)
        )).scalar_one()
    assert len(alerts) == 1
    assert det_count == 1  # dedup: one detection id for the day
    assert alerts[0].severity == "high"


async def test_detections_do_not_leak_across_tenants(
    engine: tuple[DetectionEngine, _CaptureProducer], clean: Database
) -> None:
    eng, _ = engine
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    await _seed_tenant(clean, t1)
    await _seed_tenant(clean, t2)
    base = datetime.now(UTC) - timedelta(minutes=1)
    for i in range(6):
        await eng.handle(_record(_auth_failure(t1, "alice", at=base + timedelta(seconds=i))))

    async with clean.transaction() as s:
        t2_dets = (await s.execute(
            select(func.count()).select_from(Detection).where(Detection.tenant_id == t2)
        )).scalar_one()
    assert t2_dets == 0
