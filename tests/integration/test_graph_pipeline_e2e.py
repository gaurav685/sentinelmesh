"""End-to-end, real infra: events.canonical -> stream-processor -> graph.commands
-> graph-service -> Neo4j (+ graph.events), then a query round-trip.

Needs the bus and the graph store:

    docker compose -f deploy/docker/docker-compose.yml --profile bus --profile graph \
        up -d redpanda neo4j
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.clock import utcnow
from sm_common.graph import Graph
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
from sm_graph_service.engine import GraphEngine
from sm_graph_service.metrics import GraphMetrics
from sm_graph_service.repository import GraphRepository
from sm_graph_service.topics import COMMANDS_TOPIC, EVENTS_TOPIC
from sm_graph_service.writer import GraphWriter
from sm_stream_processor.engine import StreamEngine
from sm_stream_processor.metrics import StreamMetrics
from sm_stream_processor.topics import CANONICAL_TOPIC

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
async def producer() -> AsyncIterator[EventBusProducer]:
    if not await _kafka_reachable():
        msg = f"Kafka/Redpanda not reachable at {BOOTSTRAP}"
        if REQUIRE:
            pytest.fail(msg)
        pytest.skip(msg)
    p = EventBusProducer(bootstrap_servers=BOOTSTRAP, client_id="it-e2e-producer")
    await p.start()
    try:
        yield p
    finally:
        await p.stop()


def _canonical_auth() -> bytes:
    occurred = utcnow()
    raw_id = uuid7()
    actor = EntityRef(kind=EntityKind.identity, value="e2e-alice")
    target = EntityRef(kind=EntityKind.host, value="e2e-web01")
    payload = CanonicalEventPayload(
        kind=CanonicalKind.auth, occurred_at=occurred, action="authentication_succeeded",
        outcome="allow", actor=actor, target=target, entities=[actor, target],
        raw_event_id=raw_id, raw_event_type=EventType.telemetry_auth_event,
        attributes={"auth_type": "password"},
    )
    env = EventEnvelope[CanonicalEventPayload](
        event_id=uuid7(), event_type=EventType.event_canonical, event_version=1,
        occurred_at=occurred, ingested_at=utcnow(), producer="normalization-engine@0.1.0",
        tenant_id=TENANT_ID, source=EventSource(type=SourceType.sensor, sensor_id=uuid7()),
        correlation_id=uuid7(), partition_key=make_partition_key(TENANT_ID, "e2e-alice"),
        payload=payload, metadata={"raw_event_id": str(raw_id)},
    )
    return env.model_dump_json().encode()


async def _drain_through(
    topics: list[str], group: str, handler: RecordProcessor, *, quiet_polls: int = 3, budget_s: float = 40.0
) -> int:
    """Process every record on `topics` from the beginning (the group is fresh),
    stopping after `quiet_polls` consecutive empty polls or the time budget. Other
    tests' history on the shared broker is harmless — it is re-applied idempotently
    and this test asserts only on its own `TENANT_ID`."""
    consumer = EventBusConsumer(
        topics=topics, bootstrap_servers=BOOTSTRAP, group_id=group, client_id="it-e2e",
    )
    await consumer.start()
    handled = 0
    idle = 0
    try:
        deadline = time.monotonic() + budget_s
        while idle < quiet_polls and time.monotonic() < deadline:
            n = await consumer.run_once(handler, timeout_ms=2000)  # type: ignore[arg-type]
            handled += n
            idle = idle + 1 if n == 0 else 0
        return handled
    finally:
        await consumer.stop()


async def test_full_graph_pipeline(producer: EventBusProducer, graph: Graph) -> None:
    base = build_metrics("e2e")

    stream = RecordProcessor(
        producer=producer, consumer_group="it-e2e-stream",
        handle=StreamEngine(
            producer=producer, metrics=base, stream_metrics=StreamMetrics(base, "stream-processor")
        ).handle,
        metrics=base, service_name="stream-processor", max_attempts=3,
    )
    graph_proc = RecordProcessor(
        producer=producer, consumer_group="it-e2e-graph",
        handle=GraphEngine(
            writer=GraphWriter(graph), producer=producer,
            metrics=base, graph_metrics=GraphMetrics(base, "graph-service"),
        ).handle,
        metrics=base, service_name="graph-service", max_attempts=3,
    )

    # 1. canonical event onto events.canonical
    raw = _canonical_auth()
    raw_event_id = json.loads(raw)["payload"]["raw_event_id"]
    await producer.send(CANONICAL_TOPIC, key="k", value=raw)

    # 2. stream-processor: events.canonical -> graph.commands
    assert await _drain_through([CANONICAL_TOPIC], f"it-e2e-stream-{uuid7()}", stream) >= 1

    # 3. graph-service: graph.commands -> Neo4j + graph.events
    assert await _drain_through([COMMANDS_TOPIC], f"it-e2e-graph-{uuid7()}", graph_proc) >= 3

    # 4. the graph now has the identity, the host, and the AUTHENTICATED_TO edge
    repo = GraphRepository(graph, max_rows=100, max_depth=6)
    identity = await repo.entity(TENANT_ID, ":Identity", "e2e-alice")
    assert identity is not None and identity.properties["identity_id"] == "e2e-alice"

    view = await repo.neighbors(TENANT_ID, ":Identity", "e2e-alice", depth=1)
    assert {tuple(n.labels) for n in view.nodes} == {("Identity",), ("Host",)}
    assert {e.type for e in view.edges} == {"AUTHENTICATED_TO"}

    path = await repo.attack_path(TENANT_ID, (":Identity", "e2e-alice"), (":Host", "e2e-web01"))
    assert path.found and path.length == 1

    # 5. graph.events was emitted, keyed by the source lineage
    events = await _drain_events(raw_event_id)
    assert events, "no graph.events emitted"
    outcomes = {json.loads(e)["payload"]["outcome"] for e in events}
    assert outcomes <= {"APPLIED", "DUPLICATE", "STALE"}
    assert "APPLIED" in outcomes


async def _drain_events(raw_event_id: str, *, timeout_s: float = 15.0) -> list[bytes]:
    consumer = AIOKafkaConsumer(
        EVENTS_TOPIC, bootstrap_servers=BOOTSTRAP, group_id=f"it-e2e-drain-{uuid7()}",
        auto_offset_reset="earliest", enable_auto_commit=False,
    )
    await consumer.start()
    hits: list[bytes] = []
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for msgs in (await consumer.getmany(timeout_ms=1000)).values():
                hits.extend(
                    m.value for m in msgs
                    if json.loads(m.value)["payload"].get("raw_event_id") == raw_event_id
                )
            if hits:
                break
        return hits
    finally:
        await consumer.stop()
