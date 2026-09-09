"""End-to-end: telemetry.raw -> normalization-engine -> events.canonical.

Needs a Kafka broker only (no Postgres/Redis):

    docker compose -f deploy/docker/docker-compose.yml --profile bus up -d redpanda
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from aiokafka.structs import ConsumerRecord

from sm_common.bus import EventBusConsumer, EventBusProducer
from sm_common.clock import utcnow
from sm_common.ids import uuid7
from sm_common.observability import build_metrics
from sm_contracts import EventEnvelope, EventSource, EventType, SourceType, make_partition_key
from sm_contracts.telemetry import NetworkFlowPayload
from sm_normalization_engine.engine import NormalizationEngine
from sm_normalization_engine.metrics import NormalizationMetrics
from sm_normalization_engine.topics import CANONICAL_TOPIC, DLQ_TOPIC, RAW_TOPIC

pytestmark = pytest.mark.integration

REQUIRE = os.environ.get("SM_REQUIRE_INTEGRATION") == "1"
BOOTSTRAP = os.environ.get("SM_TEST_KAFKA_BOOTSTRAP", "localhost:19092")
TENANT_ID = uuid7()


async def _kafka_reachable() -> bool:
    producer = EventBusProducer(bootstrap_servers=BOOTSTRAP, client_id="it-probe")
    try:
        await asyncio.wait_for(producer.start(), timeout=5)
        await asyncio.wait_for(producer.ping(), timeout=5)
        return True
    except (KafkaConnectionError, TimeoutError, OSError):
        return False
    finally:
        await producer.stop()


@pytest_asyncio.fixture
async def kafka_ready() -> None:
    if not await _kafka_reachable():
        msg = f"Kafka/Redpanda not reachable at {BOOTSTRAP}"
        if REQUIRE:
            pytest.fail(f"SM_REQUIRE_INTEGRATION=1 but {msg}")
        pytest.skip(msg)


@pytest_asyncio.fixture
async def producer(kafka_ready: None) -> AsyncIterator[EventBusProducer]:
    p = EventBusProducer(bootstrap_servers=BOOTSTRAP, client_id="it-normalization-producer")
    await p.start()
    try:
        yield p
    finally:
        await p.stop()


@pytest_asyncio.fixture
async def engine(producer: EventBusProducer) -> NormalizationEngine:
    base = build_metrics("normalization-engine")
    return NormalizationEngine(
        producer=producer, consumer_group="it-normalization", metrics=base,
        norm_metrics=NormalizationMetrics(base, "normalization-engine"), produce_attempts=3,
    )


def _raw_flow(**over: object) -> bytes:
    occurred = utcnow()
    payload = NetworkFlowPayload(
        occurred_at=occurred.isoformat(), src_ip="10.7.7.7", dst_ip="8.8.8.8",
        protocol="tcp", dst_port=443,
    )
    env = EventEnvelope[NetworkFlowPayload](
        event_id=uuid7(), event_type=EventType.telemetry_network_flow, event_version=1,
        occurred_at=occurred, ingested_at=utcnow(), producer="ingestion-gateway@0.1.0",
        tenant_id=TENANT_ID, source=EventSource(type=SourceType.sensor, sensor_id=uuid7()),
        correlation_id=uuid7(), partition_key=make_partition_key(TENANT_ID, "10.7.7.7"),
        payload=payload,
    )
    return env.model_dump_json().encode()


async def _drain(
    topic: str, match: Callable[[ConsumerRecord], bool], *, timeout_s: float = 20.0
) -> ConsumerRecord | None:
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=BOOTSTRAP, group_id=f"it-{uuid7()}",
        auto_offset_reset="earliest", enable_auto_commit=False,
    )
    await consumer.start()
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for msgs in (await consumer.getmany(timeout_ms=1000)).values():
                for m in msgs:
                    if match(m):
                        return m
        return None
    finally:
        await consumer.stop()


async def _process_raw(
    group: str, handler: Callable[[ConsumerRecord], object], *, expect: int, timeout_s: float = 25.0
) -> int:
    """One consumer, polled until `expect` records are handled or time runs out."""
    consumer = EventBusConsumer(
        topics=[RAW_TOPIC], bootstrap_servers=BOOTSTRAP, group_id=group,
        client_id="it-normalization-consumer",
    )
    await consumer.start()
    handled = 0
    try:
        deadline = time.monotonic() + timeout_s
        while handled < expect and time.monotonic() < deadline:
            handled += await consumer.run_once(handler, timeout_ms=2000)  # type: ignore[arg-type]
        return handled
    finally:
        await consumer.stop()


async def test_raw_flow_becomes_canonical_on_events_canonical(
    producer: EventBusProducer, engine: NormalizationEngine
) -> None:
    group = f"it-normalization-{uuid7()}"

    raw = _raw_flow()
    source_event_id = json.loads(raw)["event_id"]
    await producer.send(RAW_TOPIC, key="k", value=raw)

    assert await _process_raw(group, engine.handle, expect=1) >= 1

    def _match(m: ConsumerRecord) -> bool:
        try:
            return json.loads(m.value)["metadata"].get("raw_event_id") == source_event_id
        except (ValueError, KeyError):
            return False

    msg = await _drain(CANONICAL_TOPIC, _match)
    assert msg is not None, "no canonical event produced"
    doc = json.loads(msg.value)
    assert doc["event_type"] == "event.canonical"
    assert doc["producer"].startswith("normalization-engine@")
    assert doc["tenant_id"] == str(TENANT_ID)
    assert doc["payload"]["kind"] == "network_flow"
    assert doc["payload"]["raw_event_id"] == source_event_id
    assert msg.key.decode() == doc["partition_key"]


async def test_poison_record_goes_to_dlq_and_next_good_record_still_processes(
    producer: EventBusProducer, engine: NormalizationEngine
) -> None:
    group = f"it-normalization-{uuid7()}"

    marker = f"it-poison-{uuid7()}".encode()
    await producer.send(RAW_TOPIC, key="p", value=b'{"broken":true,"m":"' + marker + b'"}')
    good = _raw_flow()
    good_id = json.loads(good)["event_id"]
    await producer.send(RAW_TOPIC, key="g", value=good)

    assert await _process_raw(group, engine.handle, expect=2) >= 2

    dlq = await _drain(DLQ_TOPIC, lambda m: marker in m.value)
    assert dlq is not None, "poison record not dead-lettered"
    wrapped = json.loads(dlq.value)
    assert wrapped["error_type"] in {"unparseable", "envelope_invalid"}
    assert wrapped["consumer_group"] == "it-normalization"  # the engine's configured group

    canonical = await _drain(
        CANONICAL_TOPIC,
        lambda m: json.loads(m.value)["metadata"].get("raw_event_id") == good_id,
    )
    assert canonical is not None, "good record after a poison record was not processed"
