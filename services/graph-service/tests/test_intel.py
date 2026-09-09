from __future__ import annotations

import uuid
from typing import Any

import pytest

from sm_graph_service.intel import analyse_neighbourhood
from sm_graph_service.repository import GraphEdgeView, GraphNodeView, GraphView

from .conftest import internal_token

TENANT = uuid.uuid4()


def _auth(**kw: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {internal_token(TENANT, **kw)}"}


def _star_view(n_spokes: int = 12) -> GraphView:
    nodes = [GraphNodeView(id="hub", labels=["Host"], properties={})]
    edges = []
    for i in range(n_spokes):
        nodes.append(GraphNodeView(id=f"s{i}", labels=["Identity"], properties={}))
        edges.append(GraphEdgeView(src=f"s{i}", dst="hub", type="AUTHENTICATED_TO", properties={}))
    return GraphView(nodes=nodes, edges=edges, truncated=False)


# ---- the analysis is pure + deterministic --------------------------
def test_analyse_flags_the_hub_and_finds_one_cluster() -> None:
    intel = analyse_neighbourhood(_star_view(15), label=":Host", key="hub", z_threshold=3.0)
    assert intel.node_count == 16
    assert "hub" in {a.node_id for a in intel.anomalies}
    assert len(intel.clusters) == 1
    assert set(intel.methods) == {"anomaly", "clustering", "subgraph"}
    again = analyse_neighbourhood(_star_view(15), label=":Host", key="hub", z_threshold=3.0)
    assert intel == again


def test_analyse_drops_edges_to_nodes_outside_the_capped_view() -> None:
    view = GraphView(
        nodes=[GraphNodeView(id="a", labels=["Host"], properties={})],
        edges=[GraphEdgeView(src="a", dst="beyond_the_cap", type="X", properties={})],
        truncated=True,
    )
    intel = analyse_neighbourhood(view, label=":Host", key="a", z_threshold=3.5)
    assert intel.edge_count == 0
    assert intel.truncated is True


def test_analyse_rejects_an_empty_neighbourhood() -> None:
    with pytest.raises(ValueError):
        analyse_neighbourhood(
            GraphView(nodes=[], edges=[], truncated=False), label=":Host", key="x", z_threshold=3.5
        )


# ---- the API endpoint -------------------------------------------
def test_intel_endpoint_returns_findings(app_client: Any) -> None:
    app_client.fake_graph.read_plan = [
        [{"id": "hub", "labels": ["Host"], "props": {"host_id": "hub", "uid": "z"}}],  # entity()
        [  # neighbors() node rows
            {"id": "hub", "labels": ["Host"], "props": {"host_id": "hub"}},
            {"id": "a", "labels": ["Identity"], "props": {"identity_id": "a"}},
            {"id": "b", "labels": ["Identity"], "props": {"identity_id": "b"}},
        ],
        [  # neighbors() edge rows
            {"src": "a", "dst": "hub", "type": "AUTHENTICATED_TO", "props": {}},
            {"src": "b", "dst": "hub", "type": "AUTHENTICATED_TO", "props": {}},
        ],
    ]
    r = app_client.get(
        "/api/v1/graph/intel", params={"label": ":Host", "key": "hub", "depth": 2}, headers=_auth()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["node_count"] == 3
    assert body["feature_schema_version"] == "1"
    assert set(body["methods"]) == {"anomaly", "clustering", "subgraph"}


def test_intel_endpoint_is_404_for_a_missing_entity(app_client: Any) -> None:
    app_client.fake_graph.read_plan = [[]]  # entity() finds nothing
    r = app_client.get(
        "/api/v1/graph/intel", params={"label": ":Host", "key": "ghost"}, headers=_auth()
    )
    assert r.status_code == 404


def test_intel_endpoint_requires_a_token(app_client: Any) -> None:
    assert app_client.get(
        "/api/v1/graph/intel", params={"label": ":Host", "key": "hub"}
    ).status_code == 401
