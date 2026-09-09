"""Test rig for graph-service — no broker, no Neo4j.

The real MERGE semantics (applied / stale / duplicate, cross-tenant, missing
nodes, out-of-order) are exercised against a real Neo4j in
`tests/integration/test_graph_service_neo4j.py`. These unit tests cover the
allowlist guard, key validation, envelope parsing, and error mapping with a fake
graph that just records the Cypher it was handed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiokafka.structs import ConsumerRecord

from sm_common.config import AppSettings
from sm_common.graph import GraphUnavailableError
from sm_common.ids import uuid7
from sm_common.observability import build_metrics
from sm_contracts import (
    EventEnvelope,
    EventSource,
    EventType,
    GraphCommandPayload,
    GraphEndpoint,
    GraphOp,
    SourceType,
    graph_command_id,
    make_partition_key,
)
from sm_graph_service.engine import GraphEngine
from sm_graph_service.metrics import GraphMetrics
from sm_graph_service.writer import GraphWriter

TENANT_ID = uuid7()


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeGraph:
    """Records queries; returns queued rows. `unavailable=True` makes every call
    raise `GraphUnavailableError`."""

    def __init__(self) -> None:
        self.reads: list[tuple[str, dict[str, Any]]] = []
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.applied_ids: set[str] = set()
        self.write_rows: list[dict[str, Any]] = [{"current": True}]
        self.read_plan: list[list[dict[str, Any]]] = []
        self.unavailable = False

    async def ping(self) -> None:
        if self.unavailable:
            raise GraphUnavailableError("down")

    async def run_read(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.unavailable:
            raise GraphUnavailableError("down")
        params = params or {}
        self.reads.append((cypher, params))
        if "_GraphCommand" in cypher and params.get("cid") in self.applied_ids:
            return [{"id": params["cid"]}]
        if self.read_plan:
            return self.read_plan.pop(0)
        return []

    async def run_write(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.unavailable:
            raise GraphUnavailableError("down")
        params = params or {}
        self.writes.append((cypher, params))
        if "MERGE (c:_GraphCommand" in cypher:
            self.applied_ids.add(params["cid"])
            return []
        return list(self.write_rows)


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bytes]] = []
        self.fail_topics: set[str] = set()

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...

    async def send(self, topic: str, *, key: str, value: bytes, headers: Any = None) -> None:
        if topic in self.fail_topics:
            raise ConnectionError("broker down")
        self.sent.append((topic, key, value))

    def to(self, topic: str) -> list[dict[str, Any]]:
        return [json.loads(v) for t, _k, v in self.sent if t == topic]


class FakeConsumer:
    group_id = "graph-writer"

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...
    async def run(self, handler: Any) -> None: ...


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def node_command(
    *, label: str = ":Host", key: dict[str, Any] | None = None,
    props: dict[str, Any] | None = None, observed_at: datetime | None = None,
    op: GraphOp = GraphOp.merge_node, tenant_id: Any = None,
) -> GraphCommandPayload:
    key = key if key is not None else {"host_id": "web01"}
    raw_id = uuid7()
    disc = f"{label}:{next(iter(key.values()), '')}"
    return GraphCommandPayload(
        command_id=graph_command_id(raw_id, op, label, disc),
        op=op, tenant_id=tenant_id or TENANT_ID,
        observed_at=observed_at or (datetime.now(UTC) - timedelta(seconds=5)),
        raw_event_id=raw_id, label=label, key=key, props=props or {},
    )


def edge_command(
    *, label: str = "CONNECTED_TO",
    start: GraphEndpoint | None = None, end: GraphEndpoint | None = None,
    props: dict[str, Any] | None = None, observed_at: datetime | None = None,
) -> GraphCommandPayload:
    start = start or GraphEndpoint(label=":Host", key={"host_id": "web01"})
    end = end or GraphEndpoint(label=":IpAddress", key={"ip": "10.0.0.9"})
    raw_id = uuid7()
    return GraphCommandPayload(
        command_id=graph_command_id(raw_id, GraphOp.merge_edge, label, "d"),
        op=GraphOp.merge_edge, tenant_id=TENANT_ID,
        observed_at=observed_at or (datetime.now(UTC) - timedelta(seconds=5)),
        raw_event_id=raw_id, label=label, start=start, end=end, props=props or {},
    )


def envelope_for(cmd: GraphCommandPayload) -> EventEnvelope[GraphCommandPayload]:
    return EventEnvelope[GraphCommandPayload](
        event_id=cmd.command_id, event_type=EventType.graph_command, event_version=1,
        occurred_at=cmd.observed_at, ingested_at=datetime.now(UTC),
        producer="stream-processor@0.1.0", tenant_id=cmd.tenant_id,
        source=EventSource(type=SourceType.sensor, sensor_id=uuid7()),
        correlation_id=uuid7(),
        partition_key=make_partition_key(cmd.tenant_id, str(cmd.raw_event_id)),
        payload=cmd, metadata={},
    )


_TEST_JWT_KEY = "graph-service-test-signing-key-0123456789"


def internal_token(tenant_id: Any, *, key: str = _TEST_JWT_KEY, audience: str = "graph-service") -> str:
    from sm_common.security import mint_internal_token

    return mint_internal_token(
        signing_key=key, subject="api-gateway", tenant_id=tenant_id, audience=audience
    )


def make_record(value: bytes) -> ConsumerRecord:
    return ConsumerRecord(
        topic="graph.commands", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=value, checksum=None, serialized_key_size=0,
        serialized_value_size=len(value), headers=(),
    )


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@dataclass
class Rig:
    engine: GraphEngine
    writer: GraphWriter
    graph: FakeGraph
    producer: FakeProducer
    metrics: Any = field(default=None)


@pytest.fixture
def rig() -> Rig:
    base = build_metrics("graph-service")
    gm = GraphMetrics(base, "graph-service")
    graph = FakeGraph()
    producer = FakeProducer()
    writer = GraphWriter(graph)  # type: ignore[arg-type]
    engine = GraphEngine(
        writer=writer, producer=producer,  # type: ignore[arg-type]
        metrics=base, graph_metrics=gm,
    )
    return Rig(engine=engine, writer=writer, graph=graph, producer=producer, metrics=base)


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "graph-service", "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY, "oidc_client_secret": "s",
        "neo4j_password": "x", "kafka_consumer_group": "graph-writer",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


@pytest.fixture
def app_client() -> AsyncIterator[Any]:
    from fastapi.testclient import TestClient

    from sm_common.bus import RecordProcessor
    from sm_graph_service.app import create_app
    from sm_graph_service.deps import Services
    from sm_graph_service.repository import GraphRepository

    base = build_metrics("graph-service")
    gm = GraphMetrics(base, "graph-service")
    graph = FakeGraph()
    producer = FakeProducer()
    writer = GraphWriter(graph)  # type: ignore[arg-type]
    engine = GraphEngine(writer=writer, producer=producer, metrics=base, graph_metrics=gm)  # type: ignore[arg-type]
    processor = RecordProcessor(
        producer=producer, consumer_group="graph-writer", handle=engine.handle,  # type: ignore[arg-type]
        metrics=base, service_name="graph-service",
    )
    services = Services(
        settings=build_settings(), metrics=base, graph_metrics=gm, graph=graph,  # type: ignore[arg-type]
        repository=GraphRepository(graph, max_rows=1000, max_depth=8),  # type: ignore[arg-type]
        producer=producer, consumer=FakeConsumer(), engine=engine, processor=processor,
    )
    app = create_app(services=services)
    with TestClient(app) as c:
        c.fake_graph = graph  # type: ignore[attr-defined]
        yield c
