"""End-to-end: events.canonical -> stream-processor -> graph.commands.

Needs a Kafka broker only:

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

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.clock import utcnow
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
from sm_stream_processor.topics import CANONICAL_TOPIC, DLQ_TOPIC, GRAPH_COMMANDS_TOPIC

pytestmark = pytest.mark.integration

REQUIRE = os.environ.get("SM_REQUIRE_INTEGRATION") == "1"
BOOTSTRAP = os.environ.get("SM_TEST_KAFKA_BOOTSTRAP", "localhost:19092")
TENANT_ID = uuid7()


async def _kafka_reachable() -> bool:
    p = EventBusProducer(bootstrap_servers=BOOTSTRAP, client_id="it-probe")
    try:
        await asyncio.wait_for(p.start(), timeout=5)
        await asyncio.wait_for(p.ping(), timeout=5)
        return True
    except (KafkaConnectionError, TimeoutError, OSError):
        return False
    finally:
        await p.stop()


@pytest_asyncio.fixture
async def kafka_ready() -> None:
    if not await _kafka_reachable():
        msg = f"Kafka/Redpanda not reachable at {BOOTSTRAP}"
        if REQUIRE:
            pytest.fail(f"SM_REQUIRE_INTEGRATION=1 but {msg}")
        pytest.skip(msg)


@pytest_asyncio.fixture
async def producer(kafka_ready: None) -> AsyncIterator[EventBusProducer]:
    p = EventBusProducer(bootstrap_servers=BOOTSTRAP, client_id="it-sp-producer")
    await p.start()
    try:
        yield p
    finally:
        await p.stop()


@pytest_asyncio.fixture
async def processor(producer: EventBusProducer) -> RecordProcessor:
    base = build_metrics("stream-processor")
    engine = StreamEngine(
        producer=producer, metrics=base, stream_metrics=StreamMetrics(base, "stream-processor")
    )
    return RecordProcessor(
        producer=producer, consumer_group="it-stream", handle=engine.handle,
        metrics=base, service_name="stream-processor", max_attempts=3,
    )


def _canonical(**over: object) -> bytes:
    occurred = utcnow()
    raw_id = uuid7()
    actor = EntityRef(kind=EntityKind.ip, value="10.7.7.7")
    target = EntityRef(kind=EntityKind.ip, value="8.8.8.8")
    payload = CanonicalEventPayload(
        kind=CanonicalKind.network_flow, occurred_at=occurred, action="connected_to",
        outcome="allow", actor=actor, target=target, entities=[actor, target],
        raw_event_id=raw_id, raw_event_type=EventType.telemetry_network_flow,
        attributes={"dst_port": 443, "protocol": "tcp"},
    )
    env = EventEnvelope[CanonicalEventPayload](
        event_id=uuid7(), event_type=EventType.event_canonical, event_version=1,
        occurred_at=occurred, ingested_at=utcnow(), producer="normalization-engine@0.1.0",
        tenant_id=TENANT_ID, source=EventSource(type=SourceType.sensor, sensor_id=uuid7()),
        correlation_id=uuid7(), partition_key=make_partition_key(TENANT_ID, "10.7.7.7"),
        payload=payload, metadata={"raw_event_id": str(raw_id)},
    )
    return env.model_dump_json().encode()


async def _drain(
    topic: str, match: Callable[[ConsumerRecord], bool], *, want: int = 1, timeout_s: float = 20.0
) -> list[ConsumerRecord]:
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=BOOTSTRAP, group_id=f"it-{uuid7()}",
        auto_offset_reset="earliest", enable_auto_commit=False,
    )
    await consumer.start()
    hits: list[ConsumerRecord] = []
    try:
        deadline = time.monotonic() + timeout_s
        while len(hits) < want and time.monotonic() < deadline:
            for msgs in (await consumer.getmany(timeout_ms=1000)).values():
                hits.extend(m for m in msgs if match(m))
        return hits
    finally:
        await consumer.stop()


async def _process(group: str, handler: RecordProcessor, *, expect: int, timeout_s: float = 25.0) -> int:
    consumer = EventBusConsumer(
        topics=[CANONICAL_TOPIC], bootstrap_servers=BOOTSTRAP, group_id=group, client_id="it-sp",
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


async def test_canonical_event_produces_graph_commands(
    producer: EventBusProducer, processor: RecordProcessor
) -> None:
    group = f"it-stream-{uuid7()}"
    raw = _canonical()
    raw_event_id = json.loads(raw)["payload"]["raw_event_id"]
    await producer.send(CANONICAL_TOPIC, key="k", value=raw)

    assert await _process(group, processor, expect=1) >= 1

    cmds = await _drain(
        GRAPH_COMMANDS_TOPIC,
        lambda m: json.loads(m.value)["payload"].get("raw_event_id") == raw_event_id,
        want=3,
    )
    assert len(cmds) >= 3  # 2 node upserts + 1 edge
    docs = [json.loads(c.value) for c in cmds]
    assert {d["event_type"] for d in docs} == {"graph.command"}
    ops = {d["payload"]["op"] for d in docs}
    assert "MERGE_NODE" in ops and "MERGE_EDGE" in ops
    edge = next(d for d in docs if d["payload"]["op"] == "MERGE_EDGE")
    assert edge["payload"]["label"] == "CONNECTED_TO"
    assert edge["payload"]["tenant_id"] == str(TENANT_ID)
    # deterministic id == the record key partition derivation holds
    assert edge["event_id"] == edge["payload"]["command_id"]


async def test_poison_canonical_record_goes_to_dlq(
    producer: EventBusProducer, processor: RecordProcessor
) -> None:
    group = f"it-stream-{uuid7()}"
    marker = f"it-sp-poison-{uuid7()}".encode()
    await producer.send(CANONICAL_TOPIC, key="p", value=b'{"event_type":"event.canonical","x":"' + marker + b'"}')
    good = _canonical()
    good_raw_id = json.loads(good)["payload"]["raw_event_id"]
    await producer.send(CANONICAL_TOPIC, key="g", value=good)

    assert await _process(group, processor, expect=2) >= 2

    dlq = await _drain(DLQ_TOPIC, lambda m: marker in m.value)
    assert dlq, "poison canonical record not dead-lettered"
    assert json.loads(dlq[0].value)["error_type"] == "poison"

    later = await _drain(
        GRAPH_COMMANDS_TOPIC,
        lambda m: json.loads(m.value)["payload"].get("raw_event_id") == good_raw_id,
    )
    assert later, "good record after a poison record was not processed"
