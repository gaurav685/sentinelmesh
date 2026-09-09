from __future__ import annotations

import uuid

import pytest

from sm_common.errors import ValidationFailed
from sm_graph_service.repository import GraphRepository

from .conftest import FakeGraph

TENANT = uuid.uuid4()


def _repo(graph: FakeGraph, *, max_rows: int = 1000, max_depth: int = 8) -> GraphRepository:
    return GraphRepository(graph, max_rows=max_rows, max_depth=max_depth)  # type: ignore[arg-type]


async def test_unknown_label_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="unknown node label"):
        await _repo(FakeGraph()).entity(TENANT, ":Wormhole", "x")


async def test_entity_query_is_tenant_scoped_and_parameterized() -> None:
    g = FakeGraph()
    g.read_plan = [[{"id": "n1", "labels": ["Host"], "props": {"host_id": "web01", "uid": "x", "_watermark": 1}}]]
    node = await _repo(g).entity(TENANT, ":Host", "web01")
    assert node is not None
    # internal props stripped
    assert node.properties == {"host_id": "web01"}
    cypher, params = g.reads[0]
    assert "web01" not in cypher  # the key value is a bound parameter
    assert params == {"tenant": str(TENANT), "key": "web01"}
    assert "{tenant_id: $tenant}" in cypher


async def test_entity_missing_returns_none() -> None:
    assert await _repo(FakeGraph()).entity(TENANT, ":Host", "nope") is None


async def test_neighbors_depth_is_clamped_to_the_server_cap() -> None:
    g = FakeGraph()
    g.read_plan = [[], []]
    await _repo(g, max_depth=3).neighbors(TENANT, ":Host", "web01", depth=99)
    node_cypher = g.reads[0][0]
    assert "-[*1..3]-" in node_cypher
    assert "-[*1..99]-" not in node_cypher


async def test_neighbors_depth_floor_is_one() -> None:
    g = FakeGraph()
    g.read_plan = [[], []]
    await _repo(g).neighbors(TENANT, ":Host", "web01", depth=0)
    assert "-[*1..1]-" in g.reads[0][0]


async def test_neighbors_row_cap_is_clamped_and_flags_truncation() -> None:
    g = FakeGraph()
    nodes = [{"id": f"n{i}", "labels": ["Host"], "props": {}} for i in range(5)]
    g.read_plan = [nodes, []]
    view = await _repo(g, max_rows=5).neighbors(TENANT, ":Host", "web01", depth=1, limit=10_000)
    assert g.reads[0][1]["cap"] == 5
    assert view.truncated is True


async def test_attack_path_not_found() -> None:
    view = await _repo(FakeGraph()).attack_path(
        TENANT, (":Host", "a"), (":Host", "b"), max_depth=4
    )
    assert view.found is False
    assert view.nodes == [] and view.edges == []


async def test_attack_path_projects_nodes_and_edges() -> None:
    g = FakeGraph()
    g.read_plan = [[
        {
            "ns": [
                {"id": "a", "labels": ["Host"], "props": {"host_id": "a", "_watermark": 1}},
                {"id": "b", "labels": ["IpAddress"], "props": {"ip": "1.1.1.1"}},
            ],
            "rs": [{"src": "a", "dst": "b", "type": "CONNECTED_TO", "props": {"port": 443}}],
            "len": 1,
        }
    ]]
    view = await _repo(g).attack_path(TENANT, (":Host", "a"), (":IpAddress", "1.1.1.1"))
    assert view.found is True
    assert view.length == 1
    assert view.nodes[0].properties == {"host_id": "a"}  # _watermark stripped
    assert view.edges[0].type == "CONNECTED_TO"
