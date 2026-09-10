"""Phase 11 Unit 1 — real Neo4j: hunt-plan compilation + execution.

Proves a validated `QueryPlan` compiles to a parameterized query that runs
read-only, tenant-scoped, and cannot see another tenant's nodes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from sm_common.graph import Graph
from sm_contracts import EntitySelector, GraphCommandPayload, GraphEndpoint, GraphOp, QueryPlan, graph_command_id
from sm_graph_service.hunt import HuntRunner
from sm_graph_service.writer import GraphWriter

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)


def _node(tenant: uuid.UUID, label: str, key: dict[str, object]) -> GraphCommandPayload:
    raw = uuid.uuid4()
    return GraphCommandPayload(
        command_id=graph_command_id(raw, GraphOp.merge_node, label, str(key)),
        op=GraphOp.merge_node, tenant_id=tenant, observed_at=_NOW, raw_event_id=raw,
        label=label, key=key, props={},
    )


def _edge(tenant: uuid.UUID, rel: str, s: GraphEndpoint, e: GraphEndpoint) -> GraphCommandPayload:
    raw = uuid.uuid4()
    return GraphCommandPayload(
        command_id=graph_command_id(raw, GraphOp.merge_edge, rel, f"{s.key}{e.key}"),
        op=GraphOp.merge_edge, tenant_id=tenant, observed_at=_NOW, raw_event_id=raw,
        label=rel, start=s, end=e, props={},
    )


def _plan(intent: str, *sel: tuple[str, str], **kw: object) -> QueryPlan:
    return QueryPlan(
        intent=intent,  # type: ignore[arg-type]
        selectors=[EntitySelector(type=t, value=v) for t, v in sel],  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


async def test_hunt_runs_and_is_tenant_scoped(graph: Graph) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    w = GraphWriter(graph)
    runner = HuntRunner(graph, max_rows=200, max_depth=3)

    # tenant A: host web01 connected to an ip and a detection
    await w.apply(_node(a, ":Host", {"host_id": "web01"}))
    await w.apply(_node(a, ":IpAddress", {"ip": "10.0.0.9"}))
    await w.apply(_node(a, ":Detection", {"detection_id": str(uuid.uuid4())}))
    await w.apply(_edge(a, "CONNECTED_TO",
                        GraphEndpoint(label=":Host", key={"host_id": "web01"}),
                        GraphEndpoint(label=":IpAddress", key={"ip": "10.0.0.9"})))
    await w.apply(_edge(a, "INVOLVES",
                        GraphEndpoint(label=":Detection", key={"detection_id": "x"}),
                        GraphEndpoint(label=":Host", key={"host_id": "web01"})))
    # tenant B: its own host web01 (same natural key)
    await w.apply(_node(b, ":Host", {"host_id": "web01"}))

    found = await runner.run(_plan("find_entity", ("host", "web01")), a)
    assert found.row_count == 1
    assert found.rows[0]["properties"]["host_id"] == "web01"

    related = await runner.run(_plan("list_related", ("host", "web01")), a)
    kinds = {next(iter(r["labels"])) for r in related.rows}
    assert "IpAddress" in kinds

    # tenant B's hunt for the same key sees only its own (bare) host
    b_related = await runner.run(_plan("list_related", ("host", "web01")), b)
    assert b_related.row_count == 0

    # a non-existent (hallucinated) entity is an honest empty result, not an error
    ghost = await runner.run(_plan("find_entity", ("host", "does-not-exist")), a)
    assert ghost.row_count == 0
    assert ghost.cypher_fingerprint == found.cypher_fingerprint
