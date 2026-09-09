"""Test rig for the normalization engine — no broker.

`FakeProducer` records sends; the engine handler is exercised directly. App /
health tests inject a `Services` with fakes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from aiokafka.structs import ConsumerRecord

from sm_common.bus import RecordProcessor
from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_common.ids import uuid7
from sm_common.observability import build_metrics
from sm_contracts import EventEnvelope, EventSource, EventType, SourceType, make_partition_key
from sm_contracts.telemetry import (
    AuthEventPayload,
    DnsQueryPayload,
    FileAccessPayload,
    NetworkFlowPayload,
    ProcessExecPayload,
)
from sm_normalization_engine.engine import NormalizationEngine
from sm_normalization_engine.metrics import NormalizationMetrics

_PAYLOAD_BY_SOURCE = {
    "network_flow": (EventType.telemetry_network_flow, NetworkFlowPayload),
    "auth_event": (EventType.telemetry_auth_event, AuthEventPayload),
    "dns_query": (EventType.telemetry_dns_query, DnsQueryPayload),
    "process_exec": (EventType.telemetry_process_exec, ProcessExecPayload),
    "file_access": (EventType.telemetry_file_access, FileAccessPayload),
}

TENANT_ID = uuid7()
SENSOR_ID = uuid7()


def make_envelope(source_type: str, **payload_fields: Any) -> EventEnvelope[Any]:
    event_type, model = _PAYLOAD_BY_SOURCE[source_type]
    occurred = utcnow() - timedelta(seconds=1)
    payload = model(occurred_at=occurred.isoformat(), **payload_fields)
    return EventEnvelope[model](  # type: ignore[valid-type]
        event_id=uuid7(),
        event_type=event_type,
        event_version=1,
        occurred_at=occurred,
        ingested_at=utcnow(),
        producer="ingestion-gateway@0.1.0",
        tenant_id=TENANT_ID,
        source=EventSource(type=SourceType.sensor, sensor_id=SENSOR_ID),
        correlation_id=uuid7(),
        partition_key=make_partition_key(TENANT_ID, "x"),
        payload=payload,
    )


def make_record(value: bytes, *, key: bytes | None = b"k", partition: int = 0, offset: int = 0) -> ConsumerRecord:
    return ConsumerRecord(
        topic="telemetry.raw", partition=partition, offset=offset, timestamp=0,
        timestamp_type=0, key=key, value=value, checksum=None,
        serialized_key_size=0, serialized_value_size=len(value), headers=(),
    )


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bytes]] = []
        self.fail = False
        self.fail_topics: set[str] = set()
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

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
    def __init__(self) -> None:
        self.group_id = "normalization"
        self.fail = False

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def ping(self) -> None:
        if self.fail:
            raise ConnectionError("broker down")

    async def run(self, handler: Any) -> None: ...


@dataclass
class Rig:
    engine: NormalizationEngine
    processor: RecordProcessor
    producer: FakeProducer
    base_metrics: Any
    metrics: NormalizationMetrics
    consumed: list[Any] = field(default_factory=list)


@pytest.fixture
def make_envelope_fn() -> Any:
    return make_envelope


@pytest.fixture
def make_record_fn() -> Any:
    return make_record


@pytest.fixture
def rig() -> Rig:
    base = build_metrics("normalization-engine")
    nm = NormalizationMetrics(base, "normalization-engine")
    producer = FakeProducer()
    engine = NormalizationEngine(
        producer=producer,  # type: ignore[arg-type]
        consumer_group="normalization",
        metrics=base,
        norm_metrics=nm,
    )
    processor = RecordProcessor(
        producer=producer,  # type: ignore[arg-type]
        consumer_group="normalization", handle=engine.handle,
        metrics=base, service_name="normalization-engine", max_attempts=2, backoff_cap_s=0.0,
    )
    return Rig(engine=engine, processor=processor, producer=producer, base_metrics=base, metrics=nm)


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "normalization-engine",
        "pg_password": "x",
        "internal_jwt_signing_key": "k",
        "oidc_client_secret": "s",
        "neo4j_password": "x",
        "kafka_consumer_group": "normalization",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


@pytest.fixture
def app_client() -> AsyncIterator[Any]:
    from fastapi.testclient import TestClient

    from sm_normalization_engine.app import create_app
    from sm_normalization_engine.deps import Services

    base = build_metrics("normalization-engine")
    nm = NormalizationMetrics(base, "normalization-engine")
    producer = FakeProducer()
    consumer = FakeConsumer()
    engine = NormalizationEngine(
        producer=producer, consumer_group="normalization", metrics=base, norm_metrics=nm  # type: ignore[arg-type]
    )
    processor = RecordProcessor(
        producer=producer, consumer_group="normalization", handle=engine.handle,  # type: ignore[arg-type]
        metrics=base, service_name="normalization-engine",
    )
    services = Services(
        settings=build_settings(), metrics=base, norm_metrics=nm,
        producer=producer, consumer=consumer, engine=engine, processor=processor,  # type: ignore[arg-type]
    )
    app = create_app(services=services)
    with TestClient(app) as c:
        yield c
