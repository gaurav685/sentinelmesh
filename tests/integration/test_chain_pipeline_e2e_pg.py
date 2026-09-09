"""Phase 7 Unit 3 — real PostgreSQL (+ optional real Neo4j): the correlation chain.

    events.canonical -> detection-engine -> detections
                     -> correlation-engine -> attack_chain / attack_chain_stage
                                            -> threat_score  (correlation-engine is the sole writer)
                                            -> graph.commands (:AttackChain / INVOLVES / MAPPED_TO)

The graph commands are then applied to a real Neo4j (when the `graph` profile is
up) so the projected `:AttackChain` node and its edges are asserted end to end.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from aiokafka.structs import ConsumerRecord
from sm_correlation_engine.chains import ChainRepository
from sm_correlation_engine.engine import CorrelationHandler
from sm_correlation_engine.metrics import CorrelationMetrics
from sm_detection_engine.engine import DetectionEngine
from sm_detection_engine.metrics import DetectionMetrics
from sm_detection_engine.repository import DetectionRepository
from sqlalchemy import select, text

from sm_common.db import AttackChainRow, Database, ThreatScore
from sm_common.graph import Graph
from sm_common.observability import build_metrics
from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EntityRef,
    EventEnvelope,
    EventSource,
    EventType,
    GraphCommandPayload,
    SourceType,
    make_partition_key,
)

from .conftest import integration_settings

pytestmark = pytest.mark.integration


class _NoModel:
    async def score(self, *_a: object, **_kw: object) -> None:
        return None


class _Capture:
    def __init__(self) -> None:
        self.by_topic: dict[str, list[bytes]] = {}

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...

    async def send(self, topic: str, *, key: str, value: bytes, headers: object = None) -> None:
        self.by_topic.setdefault(topic, []).append(value)


def _auth_failure(tenant: uuid.UUID, principal: str, *, at: datetime) -> EventEnvelope[CanonicalEventPayload]:
    actor = EntityRef(kind="identity", value=principal)
    target = EntityRef(kind="host", value="dc01")
    raw = uuid.uuid4()
    payload = CanonicalEventPayload(
        kind=CanonicalKind.auth, occurred_at=at, action="authentication_failed",
        outcome="failure", actor=actor, target=target, entities=[actor, target],
        raw_event_id=raw, raw_event_type=EventType.telemetry_auth_event,
        attributes={"auth_type": "password"},
    )
    return EventEnvelope[CanonicalEventPayload](
        event_id=uuid.uuid4(), event_type=EventType.event_canonical, event_version=1,
        occurred_at=at, ingested_at=datetime.now(UTC), producer="normalization-engine@0.1.0",
        tenant_id=tenant, source=EventSource(type=SourceType.sensor, sensor_id=uuid.uuid4()),
        correlation_id=uuid.uuid4(), partition_key=make_partition_key(tenant, principal),
        payload=payload, metadata={"raw_event_id": str(raw)},
    )


def _record(topic: str, value: bytes) -> ConsumerRecord:
    return ConsumerRecord(
        topic=topic, partition=0, offset=0, timestamp=0, timestamp_type=0, key=b"k",
        value=value, checksum=None, serialized_key_size=0, serialized_value_size=len(value), headers=(),
    )


async def _seed_tenant(db: Database, tid: uuid.UUID) -> None:
    async with db.transaction() as s:
        await s.execute(
            text("INSERT INTO tenant (id, slug, name, status) VALUES (:id, :slug, 'T', 'active')"),
            {"id": tid, "slug": f"t-{tid.hex[:12]}"},
        )


async def _run_pipeline(clean: Database) -> tuple[uuid.UUID, _Capture]:
    settings = integration_settings(detection_min_samples=10, detection_window_size=64)
    tenant = uuid.uuid4()
    await _seed_tenant(clean, tenant)

    det_producer = _Capture()
    det_engine = DetectionEngine(
        settings=settings, repository=DetectionRepository(clean), producer=det_producer,  # type: ignore[arg-type]
        inference=_NoModel(), metrics=DetectionMetrics(build_metrics("detection-engine"), "detection-engine"),  # type: ignore[arg-type]
    )
    base = datetime.now(UTC) - timedelta(minutes=2)
    for i in range(6):
        await det_engine.handle(_record(
            "events.canonical",
            _auth_failure(tenant, "svc-backup", at=base + timedelta(seconds=i)).model_dump_json().encode(),
        ))

    detections = det_producer.by_topic.get("detections", [])
    assert detections, "detection-engine emitted no detection"

    corr_producer = _Capture()
    corr = CorrelationHandler(
        repo=ChainRepository(clean, window_seconds=86_400, dormant_seconds=21_600),
        producer=corr_producer,  # type: ignore[arg-type]
        metrics=CorrelationMetrics(build_metrics("correlation-engine"), "correlation-engine"),
    )
    for value in detections:
        await corr.handle(_record("detections", value))
    return tenant, corr_producer


async def test_a_detection_burst_becomes_a_chain_a_score_and_graph_commands(clean: Database) -> None:
    tenant, corr_producer = await _run_pipeline(clean)

    async with clean.transaction() as s:
        chains = (await s.execute(
            select(AttackChainRow).where(AttackChainRow.tenant_id == tenant)
        )).scalars().all()
        scores = (await s.execute(
            select(ThreatScore).where(ThreatScore.tenant_id == tenant)
        )).scalars().all()
        stages = (await s.execute(
            text("SELECT stage FROM attack_chain_stage WHERE tenant_id = :t"), {"t": tenant}
        )).scalars().all()

    assert len(chains) == 1
    assert chains[0].subject_id == "svc-backup"
    assert "credential_access" in set(stages)  # T1110 -> credential access
    assert chains[0].score > 0.0

    # correlation-engine is the sole threat_score writer now
    assert len(scores) == 1
    assert scores[0].subject_id == "svc-backup"
    assert scores[0].weights_version == "v1"  # CHAIN_SCORE_VERSION, not the detection composite

    # graph projection
    graph_cmds = [json.loads(v) for v in corr_producer.by_topic.get("graph.commands", [])]
    labels = {c["payload"]["label"] for c in graph_cmds}
    assert ":AttackChain" in labels
    assert "INVOLVES" in labels
    assert "MAPPED_TO" in labels


async def test_the_chain_projects_into_real_neo4j(clean: Database, graph: Graph) -> None:
    from sm_graph_service.writer import GraphWriter

    _, corr_producer = await _run_pipeline(clean)
    writer = GraphWriter(graph)

    for value in corr_producer.by_topic.get("graph.commands", []):
        env = json.loads(value)
        await writer.apply(GraphCommandPayload.model_validate(env["payload"]))

    rows = await graph.run_read(
        "MATCH (c:AttackChain)-[:INVOLVES]->(i:Identity) RETURN c.subject_id AS s, i.identity_id AS id"
    )
    assert rows and rows[0]["s"] == "svc-backup" and rows[0]["id"] == "svc-backup"

    mapped = await graph.run_read(
        "MATCH (c:AttackChain)-[:MAPPED_TO]->(t:AttackTechnique) RETURN t.technique_id AS tid"
    )
    assert {r["tid"] for r in mapped} == {"T1110"}
