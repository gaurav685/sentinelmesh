"""`sm_common.bus` against a real Kafka broker (Redpanda).

    docker compose -f deploy/docker/docker-compose.yml --profile bus up -d redpanda

Covers the Phase 3 Unit 2 reliability surface: topic provisioning, produce /
consume, offset-commit-after-side-effect, at-least-once duplicates, graceful
shutdown, replay by timestamp, the lag metric, and the producer error metric.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
import pytest_asyncio
from aiokafka.errors import KafkaConnectionError
from aiokafka.structs import ConsumerRecord

from sm_common.bus import EventBusConsumer, EventBusProducer, ensure_topics
from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_common.ids import uuid7
from sm_common.observability import build_metrics
from sm_contracts import TOPICS

pytestmark = pytest.mark.integration

REQUIRE = os.environ.get("SM_REQUIRE_INTEGRATION") == "1"
BOOTSTRAP = os.environ.get("SM_TEST_KAFKA_BOOTSTRAP", "localhost:19092")

RecordHandler = Callable[[ConsumerRecord], Any]


def _collect(sink: list[bytes]) -> Callable[[ConsumerRecord], Any]:
    async def _h(record: ConsumerRecord) -> None:
        sink.append(record.value)
    return _h


async def _noop(_record: ConsumerRecord) -> None:
    return None


def _settings(**over: object) -> AppSettings:
    values: dict[str, object] = {
        "service_name": "bus-it",
        "kafka_bootstrap_servers": BOOTSTRAP,
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)  # type: ignore[arg-type]


async def _reachable() -> bool:
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
    if not await _reachable():
        msg = f"Kafka/Redpanda not reachable at {BOOTSTRAP}"
        if REQUIRE:
            pytest.fail(f"SM_REQUIRE_INTEGRATION=1 but {msg}")
        pytest.skip(msg)


@pytest_asyncio.fixture
async def producer(kafka_ready: None) -> AsyncIterator[EventBusProducer]:
    p = EventBusProducer.from_settings(_settings())
    await p.start()
    try:
        yield p
    finally:
        await p.stop()


def _topic() -> str:
    return f"it.bus.{uuid7()}"


async def _consumer(topic: str, group: str, **over: Any) -> EventBusConsumer:
    c = EventBusConsumer(
        topics=[topic], bootstrap_servers=BOOTSTRAP, group_id=group, client_id="it-consumer", **over
    )
    await c.start()
    return c


# --------------------------------------------------------------------------- #
async def _partition_count(topic: str) -> int:
    from aiokafka.admin import AIOKafkaAdminClient

    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP, client_id="it-count")
    await admin.start()
    try:
        described = await admin.describe_topics([topic])
        return len(described[0]["partitions"]) if described else 0
    finally:
        await admin.close()


async def test_ensure_topics_creates_the_catalog_with_partition_counts(kafka_ready: None) -> None:
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic

    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP, client_id="it-reset")
    await admin.start()
    with contextlib.suppress(Exception):
        await admin.delete_topics(["events.canonical", "events.canonical.dlq"])
    with contextlib.suppress(Exception):  # a 1-partition topic to grow
        await admin.create_topics([NewTopic("attack_chains", num_partitions=1, replication_factor=1)])
    await admin.close()
    await asyncio.sleep(1)

    await ensure_topics(_settings())

    assert await _partition_count("events.canonical") == TOPICS["events.canonical"].partitions
    assert await _partition_count("events.canonical.dlq") >= 1
    assert await _partition_count("attack_chains") == TOPICS["attack_chains"].partitions  # grown


async def test_produce_then_consume_roundtrip(producer: EventBusProducer) -> None:
    topic, group = _topic(), f"g-{uuid7()}"
    await producer.send(topic, key="k1", value=b'{"n":1}')
    seen: list[bytes] = []
    c = await _consumer(topic, group)
    try:
        for _ in range(10):
            if await c.run_once(_collect(seen), timeout_ms=1000):
                break
    finally:
        await c.stop()
    assert seen == [b'{"n":1}']


async def test_json_serialization_roundtrips(producer: EventBusProducer) -> None:
    topic, group = _topic(), f"g-{uuid7()}"
    payload = {"event_id": str(uuid7()), "event_type": "event.canonical"}
    await producer.send(topic, key="k", value=json.dumps(payload).encode())
    seen: list[bytes] = []
    c = await _consumer(topic, group)
    try:
        for _ in range(10):
            if await c.run_once(_collect(seen), timeout_ms=1000):
                break
    finally:
        await c.stop()
    assert seen and json.loads(seen[0])["event_id"] == payload["event_id"]


async def test_offset_is_committed_only_after_the_handler_succeeds(producer: EventBusProducer) -> None:
    topic, group = _topic(), f"g-{uuid7()}"
    await producer.send(topic, key="k", value=b"one")
    seen: list[bytes] = []
    fail = {"first": True}

    async def flaky(record: ConsumerRecord) -> None:
        if fail["first"]:
            fail["first"] = False
            raise RuntimeError("downstream down")
        seen.append(record.value)

    c = await _consumer(topic, group)
    try:
        with pytest.raises(RuntimeError):
            await c.run_once(flaky, timeout_ms=2000)
        for _ in range(10):
            if await c.run_once(flaky, timeout_ms=1000):
                break
    finally:
        await c.stop()
    assert seen == [b"one"]  # redelivered exactly once after the failure

    c2 = await _consumer(topic, group)
    try:
        assert await c2.run_once(_noop, timeout_ms=2000) == 0  # offset was committed
    finally:
        await c2.stop()


async def test_at_least_once_redelivers_on_a_crash_before_commit(producer: EventBusProducer) -> None:
    topic, group = _topic(), f"g-{uuid7()}"
    await producer.send(topic, key="k", value=b"dup")
    seen: list[bytes] = []

    async def append_then_raise(record: ConsumerRecord) -> None:
        seen.append(record.value)
        raise RuntimeError("crash before commit")

    c = await _consumer(topic, group)
    try:
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await c.run_once(append_then_raise, timeout_ms=1500)
    finally:
        await c.stop()
    assert seen == [b"dup", b"dup", b"dup"]  # same record, redelivered each poll


async def test_graceful_shutdown_commits_the_in_flight_batch(producer: EventBusProducer) -> None:
    topic, group = _topic(), f"g-{uuid7()}"
    await producer.send(topic, key="k", value=b"x")
    handled: list[bytes] = []

    c = await _consumer(topic, group)
    task = asyncio.create_task(c.run(_collect(handled)))
    try:
        for _ in range(30):
            if handled:
                break
            await asyncio.sleep(0.2)
        assert handled == [b"x"]
    finally:
        c.request_stop()
        await asyncio.wait_for(task, timeout=10)
        await c.stop()

    c2 = await _consumer(topic, group)
    try:
        assert await c2.run_once(_noop, timeout_ms=2000) == 0
    finally:
        await c2.stop()


async def test_seek_by_timestamp_replays_processed_records(producer: EventBusProducer) -> None:
    topic, group = _topic(), f"g-{uuid7()}"
    t0 = utcnow()
    for i in range(3):
        await producer.send(topic, key="k", value=str(i).encode())

    first: list[bytes] = []
    c = await _consumer(topic, group)
    try:
        for _ in range(15):
            await c.run_once(_collect(first), timeout_ms=1000)
            if len(first) >= 3:
                break
        assert sorted(first) == [b"0", b"1", b"2"]

        moved = await c.seek_by_timestamp(t0)
        assert moved

        replayed: list[bytes] = []
        for _ in range(15):
            await c.run_once(_collect(replayed), timeout_ms=1000)
            if len(replayed) >= 3:
                break
        assert sorted(replayed) == [b"0", b"1", b"2"]
    finally:
        await c.stop()


async def test_lag_and_records_metrics_are_populated(producer: EventBusProducer) -> None:
    topic, group = _topic(), f"g-{uuid7()}"
    metrics = build_metrics("bus-it")
    for i in range(20):
        await producer.send(topic, key="k", value=str(i).encode())

    c = await _consumer(topic, group, metrics=metrics, service_name="bus-it", max_records_per_poll=5)
    try:
        for _ in range(6):
            await c.run_once(_noop, timeout_ms=1500)
    finally:
        await c.stop()

    body = metrics.render_latest().decode()
    assert "sm_consumer_lag{" in body
    assert "sm_consumer_records_total{" in body


async def test_producer_send_error_is_metered(kafka_ready: None) -> None:
    metrics = build_metrics("bus-it")
    p = EventBusProducer(
        bootstrap_servers="127.0.0.1:1", client_id="it-bad", send_timeout_ms=1500,
        metrics=metrics, service_name="bus-it",
    )
    with contextlib.suppress(Exception):
        await asyncio.wait_for(p.start(), timeout=4)
    with pytest.raises(RuntimeError):  # producer never started -> send fails fast, metered
        await p.send("it.nope", key="k", value=b"x")
    with contextlib.suppress(Exception):
        await asyncio.wait_for(p.stop(), timeout=3)
    assert "sm_producer_send_errors_total{" in metrics.render_latest().decode()
