"""Phase 4 Unit 2 — real Neo4j: `GraphWriter` MERGE semantics.

The unit tests in `services/graph-service/tests` cover the allowlist guard and
error mapping with a fake graph. This is where the actual Cypher runs: node and
relationship creation, `command_id` idempotency, out-of-order (`STALE`) handling,
duplicate-relationship suppression, missing-endpoint creation, and tenant
isolation.

Needs the compose `graph` profile:
    docker compose -f deploy/docker/docker-compose.yml --profile graph up -d neo4j
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from sm_common.graph import Graph
from sm_contracts import (
    GraphCommandPayload,
    GraphEndpoint,
    GraphMutationOutcome,
    GraphOp,
    graph_command_id,
)
from sm_graph_service.writer import GraphWriter

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)


def _node(
    tenant: uuid.UUID, label: str, key: dict[str, object], *,
    props: dict[str, object] | None = None, at: datetime | None = None,
) -> GraphCommandPayload:
    raw = uuid.uuid4()
    return GraphCommandPayload(
        command_id=graph_command_id(raw, GraphOp.merge_node, label, str(key)),
        op=GraphOp.merge_node, tenant_id=tenant, observed_at=at or _NOW,
        raw_event_id=raw, label=label, key=key, props=props or {},
    )


def _edge(
    tenant: uuid.UUID, rel: str, start: GraphEndpoint, end: GraphEndpoint, *,
    props: dict[str, object] | None = None, at: datetime | None = None,
) -> GraphCommandPayload:
    raw = uuid.uuid4()
    return GraphCommandPayload(
        command_id=graph_command_id(raw, GraphOp.merge_edge, rel, f"{start.key}{end.key}"),
        op=GraphOp.merge_edge, tenant_id=tenant, observed_at=at or _NOW,
        raw_event_id=raw, label=rel, start=start, end=end, props=props or {},
    )


@pytest.fixture
def writer(graph: Graph) -> GraphWriter:
    return GraphWriter(graph)


async def test_merge_node_creates_a_tenant_scoped_node(writer: GraphWriter, graph: Graph) -> None:
    tenant = uuid.uuid4()
    result = await writer.apply(_node(tenant, ":Host", {"host_id": "web01"}, props={"os": "linux"}))
    assert result.outcome is GraphMutationOutcome.applied

    rows = await graph.run_read(
        "MATCH (n:Host {uid: $uid}) RETURN n.tenant_id AS t, n.host_id AS h, n.os AS os, "
        "n.first_seen AS fs, n.last_seen AS ls",
        {"uid": f"{tenant}:web01"},
    )
    assert rows[0]["t"] == str(tenant)
    assert rows[0]["h"] == "web01"
    assert rows[0]["os"] == "linux"
    assert rows[0]["fs"] is not None and rows[0]["ls"] is not None


async def test_duplicate_command_id_is_a_noop(writer: GraphWriter, graph: Graph) -> None:
    tenant = uuid.uuid4()
    cmd = _node(tenant, ":Host", {"host_id": "web02"}, props={"os": "linux"})
    assert (await writer.apply(cmd)).outcome is GraphMutationOutcome.applied

    # same command id, different props — must not be applied
    cmd2 = cmd.model_copy(update={"props": {"os": "windows"}})
    assert (await writer.apply(cmd2)).outcome is GraphMutationOutcome.duplicate

    rows = await graph.run_read(
        "MATCH (n:Host {uid: $uid}) RETURN n.os AS os, count(*) AS c", {"uid": f"{tenant}:web02"}
    )
    assert rows[0] == {"os": "linux", "c": 1}


async def test_out_of_order_command_does_not_roll_back_properties(
    writer: GraphWriter, graph: Graph
) -> None:
    tenant = uuid.uuid4()
    newer = _node(tenant, ":Host", {"host_id": "web03"}, props={"os": "linux-6"}, at=_NOW)
    older = _node(
        tenant, ":Host", {"host_id": "web03"}, props={"os": "linux-4"},
        at=_NOW - timedelta(hours=2),
    )
    assert (await writer.apply(newer)).outcome is GraphMutationOutcome.applied
    stale = await writer.apply(older)
    assert stale.outcome is GraphMutationOutcome.stale

    rows = await graph.run_read(
        "MATCH (n:Host {uid: $uid}) RETURN n.os AS os, n.first_seen AS fs",
        {"uid": f"{tenant}:web03"},
    )
    assert rows[0]["os"] == "linux-6"  # newer value kept
    # ...but the older event still widened the first_seen bound
    assert rows[0]["fs"].to_native() <= (_NOW - timedelta(hours=1))


async def test_merge_edge_creates_both_endpoints_and_one_relationship(
    writer: GraphWriter, graph: Graph
) -> None:
    tenant = uuid.uuid4()
    cmd = _edge(
        tenant, "CONNECTED_TO",
        GraphEndpoint(label=":Host", key={"host_id": "web04"}),
        GraphEndpoint(label=":IpAddress", key={"ip": "10.1.1.1"}),
        props={"port": 443},
    )
    assert (await writer.apply(cmd)).outcome is GraphMutationOutcome.applied

    rows = await graph.run_read(
        "MATCH (s:Host {uid: $s})-[r:CONNECTED_TO]->(e:IpAddress {uid: $e}) "
        "RETURN r.tenant_id AS t, r.port AS port, r.observed_at AS oa",
        {"s": f"{tenant}:web04", "e": f"{tenant}:10.1.1.1"},
    )
    assert rows[0]["t"] == str(tenant)
    assert rows[0]["port"] == 443
    assert rows[0]["oa"] is not None


async def test_repeated_edge_commands_never_duplicate_the_relationship(
    writer: GraphWriter, graph: Graph
) -> None:
    tenant = uuid.uuid4()
    start = GraphEndpoint(label=":Identity", key={"identity_id": "alice"})
    end = GraphEndpoint(label=":Host", key={"host_id": "web05"})
    for i in range(3):
        await writer.apply(
            _edge(tenant, "AUTHENTICATED_TO", start, end, at=_NOW + timedelta(seconds=i))
        )
    rows = await graph.run_read(
        "MATCH (:Identity {uid: $s})-[r:AUTHENTICATED_TO]->(:Host {uid: $e}) RETURN count(r) AS c",
        {"s": f"{tenant}:alice", "e": f"{tenant}:web05"},
    )
    assert rows[0]["c"] == 1


async def test_relationships_never_cross_tenants(writer: GraphWriter, graph: Graph) -> None:
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    for t in (t1, t2):
        await writer.apply(
            _edge(
                t, "CONNECTED_TO",
                GraphEndpoint(label=":Host", key={"host_id": "shared"}),
                GraphEndpoint(label=":IpAddress", key={"ip": "10.9.9.9"}),
            )
        )
    # two distinct Host nodes — one per tenant — not one shared node
    rows = await graph.run_read(
        "MATCH (n:Host {host_id: 'shared'}) RETURN n.tenant_id AS t ORDER BY t"
    )
    assert sorted(r["t"] for r in rows) == sorted([str(t1), str(t2)])
    # no relationship joins the two tenants
    cross = await graph.run_read(
        "MATCH (a)-[r]->(b) WHERE a.tenant_id <> b.tenant_id RETURN count(r) AS c"
    )
    assert cross[0]["c"] == 0
