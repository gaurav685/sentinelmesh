"""Test rig for the stream processor — no broker."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from aiokafka.structs import ConsumerRecord

from sm_common.bus import RecordProcessor
from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_common.ids import uuid7
from sm_common.observability import build_metrics
from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EntityKind,
    EntityRef,
    EventEnvelope,
    EventSource,
    EventType,
    SourceType,
    make_partition_key,
)
from sm_stream_processor.engine import StreamEngine
from sm_stream_processor.metrics import StreamMetrics

TENANT_ID = uuid7()

_KIND_ROLES: dict[CanonicalKind, tuple[EntityKind, EntityKind, str]] = {
    CanonicalKind.network_flow: (EntityKind.ip, EntityKind.ip, "connected_to"),
    CanonicalKind.auth: (EntityKind.identity, EntityKind.host, "authentication_succeeded"),
    CanonicalKind.dns: (EntityKind.ip, EntityKind.domain, "resolved"),
    CanonicalKind.process_exec: (EntityKind.host, EntityKind.process, "executed"),
    CanonicalKind.file_access: (EntityKind.identity, EntityKind.file, "read"),
}


def make_canonical(
    kind: CanonicalKind, *, actor_value: str, target_value: str,
    attributes: dict[str, Any] | None = None, extra_entities: list[EntityRef] | None = None,
) -> EventEnvelope[CanonicalEventPayload]:
    actor_kind, target_kind, action = _KIND_ROLES[kind]
    actor = EntityRef(kind=actor_kind, value=actor_value)
    target = EntityRef(kind=target_kind, value=target_value)
    entities = [actor, target, *(extra_entities or [])]
    occurred = utcnow() - timedelta(seconds=1)
    raw_id = uuid7()
    payload = CanonicalEventPayload(
        kind=kind, occurred_at=occurred, action=action, outcome="allow",
        actor=actor, target=target, entities=entities,
        raw_event_id=raw_id, raw_event_type=EventType.telemetry_network_flow,
        attributes=attributes or {},
    )
    return EventEnvelope[CanonicalEventPayload](
        event_id=uuid7(), event_type=EventType.event_canonical, event_version=1,
        occurred_at=occurred, ingested_at=utcnow(), producer="normalization-engine@0.1.0",
        tenant_id=TENANT_ID, source=EventSource(type=SourceType.sensor, sensor_id=uuid7()),
        correlation_id=uuid7(), partition_key=make_partition_key(TENANT_ID, actor_value),
        payload=payload, metadata={"raw_event_id": str(raw_id)},
    )


def make_record(value: bytes, *, key: bytes | None = b"k") -> ConsumerRecord:
    return ConsumerRecord(
        topic="events.canonical", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=key, value=value, checksum=None, serialized_key_size=0,
        serialized_value_size=len(value), headers=(),
    )


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bytes]] = []
        self.fail = False
        self.fail_topics: set[str] = set()

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def ping(self) -> None:
        if self.fail:
            raise ConnectionError("broker down")

    async def send(self, topic: str, *, key: str, value: bytes, headers: Any = None) -> None:
        if self.fail or topic in self.fail_topics:
            raise ConnectionError("broker down")
        self.sent.append((topic, key, value))

    def to(self, topic: str) -> list[dict[str, Any]]:
        return [json.loads(v) for t, _k, v in self.sent if t == topic]


class FakeConsumer:
    group_id = "stream-processor"

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...
    async def run(self, handler: Any) -> None: ...


@dataclass
class Rig:
    engine: StreamEngine
    processor: RecordProcessor
    producer: FakeProducer
    base_metrics: Any


@pytest.fixture
def make_canonical_fn() -> Any:
    return make_canonical


@pytest.fixture
def make_record_fn() -> Any:
    return make_record


@pytest.fixture
def rig() -> Rig:
    base = build_metrics("stream-processor")
    sm = StreamMetrics(base, "stream-processor")
    producer = FakeProducer()
    engine = StreamEngine(producer=producer, metrics=base, stream_metrics=sm)  # type: ignore[arg-type]
    processor = RecordProcessor(
        producer=producer, consumer_group="stream-processor", handle=engine.handle,  # type: ignore[arg-type]
        metrics=base, service_name="stream-processor", max_attempts=2, backoff_cap_s=0.0,
    )
    return Rig(engine=engine, processor=processor, producer=producer, base_metrics=base)


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "stream-processor", "pg_password": "x",
        "internal_jwt_signing_key": "k", "oidc_client_secret": "s",
        "neo4j_password": "x",
        "kafka_consumer_group": "stream-processor",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


@pytest.fixture
def app_client() -> AsyncIterator[Any]:
    from fastapi.testclient import TestClient

    from sm_stream_processor.app import create_app
    from sm_stream_processor.deps import Services

    base = build_metrics("stream-processor")
    sm = StreamMetrics(base, "stream-processor")
    producer = FakeProducer()
    engine = StreamEngine(producer=producer, metrics=base, stream_metrics=sm)  # type: ignore[arg-type]
    processor = RecordProcessor(
        producer=producer, consumer_group="stream-processor", handle=engine.handle,  # type: ignore[arg-type]
        metrics=base, service_name="stream-processor",
    )
    services = Services(
        settings=build_settings(), metrics=base, stream_metrics=sm, producer=producer,  # type: ignore[arg-type]
        consumer=FakeConsumer(), engine=engine, processor=processor,
    )
    app = create_app(services=services)
    with TestClient(app) as c:
        yield c
