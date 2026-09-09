"""Phase 8 Unit 4 — real Neo4j: structural graph intelligence over a live neighbourhood."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from sm_common.graph import Graph
from sm_contracts import GraphCommandPayload, GraphEndpoint, GraphOp, graph_command_id
from sm_graph_service.intel import analyse_neighbourhood
from sm_graph_service.repository import GraphRepository
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


def _edge(tenant: uuid.UUID, rel: str, start: GraphEndpoint, end: GraphEndpoint) -> GraphCommandPayload:
    raw = uuid.uuid4()
    return GraphCommandPayload(
        command_id=graph_command_id(raw, GraphOp.merge_edge, rel, f"{start.key}{end.key}"),
        op=GraphOp.merge_edge, tenant_id=tenant, observed_at=_NOW, raw_event_id=raw,
        label=rel, start=start, end=end, props={},
    )


async def test_intel_flags_a_fan_out_hub_in_a_live_graph(graph: Graph) -> None:
    tenant = uuid.uuid4()
    writer = GraphWriter(graph)
    repo = GraphRepository(graph, max_rows=1000, max_depth=8)

    await writer.apply(_node(tenant, ":Host", {"host_id": "hub"}))
    for i in range(14):
        await writer.apply(_node(tenant, ":Identity", {"identity_id": f"user{i}"}))
        await writer.apply(_edge(
            tenant, "AUTHENTICATED_TO",
            GraphEndpoint(label=":Identity", key={"identity_id": f"user{i}"}),
            GraphEndpoint(label=":Host", key={"host_id": "hub"}),
        ))

    view = await repo.neighbors(tenant, ":Host", "hub", depth=2)
    intel = analyse_neighbourhood(view, label=":Host", key="hub", z_threshold=3.0)

    assert intel.node_count == 15
    hub_ids = {a.node_id for a in intel.anomalies}
    # the hub node's elementId is the one every edge points at
    hub_element = next(n.id for n in view.nodes if "Host" in n.labels)
    assert hub_element in hub_ids
    assert len(intel.clusters) == 1
    assert intel.clusters[0].size == 15
