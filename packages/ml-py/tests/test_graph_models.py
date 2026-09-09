from __future__ import annotations

import pytest

from sm_ml.graph import (
    ConnectedComponentClusterer,
    GraphEdge,
    GraphModelRegistry,
    GraphModelUnavailable,
    GraphNode,
    LabelPropagationClusterer,
    StructuralGraphAnomaly,
    SuspiciousSubgraphHeuristic,
    build_graph_sample,
)


def _star(n_spokes: int) -> object:
    nodes = [GraphNode("hub", "Host", 0.0, 100.0)]
    edges = []
    for i in range(n_spokes):
        nodes.append(GraphNode(f"s{i}", "Identity", 0.0, 100.0))
        edges.append(GraphEdge(f"s{i}", "hub", "AUTHENTICATED_TO", 1.0))
    return build_graph_sample(nodes, edges)


# ---- structural node anomaly ---------------------------------------
def test_structural_anomaly_is_deterministic_and_bounded() -> None:
    sample = _star(12)
    a = StructuralGraphAnomaly().score_nodes(sample)
    b = StructuralGraphAnomaly().score_nodes(sample)
    assert a == b
    assert all(0.0 <= s.normalized_score <= 1.0 for s in a.scores)
    assert a.feature_schema_version == "1"
    assert a.model_version is None


def test_structural_anomaly_flags_the_odd_node_out() -> None:
    sample = _star(15)  # one hub with 15 identical spokes -> the hub is the outlier
    result = StructuralGraphAnomaly(z_threshold=3.0).score_nodes(sample)
    flagged = {s.node_id for s in result.anomalies()}
    assert "hub" in flagged
    assert not any(sid.startswith("s") for sid in flagged)


def test_a_uniform_graph_flags_nothing() -> None:
    # a 4-cycle: every node identical -> zero MAD -> no anomaly
    nodes = [GraphNode(x, "Host", 0.0, 10.0) for x in "abcd"]
    edges = [GraphEdge(a, b, "CONNECTED_TO", 1.0) for a, b in (("a", "b"), ("b", "c"), ("c", "d"), ("d", "a"))]
    result = StructuralGraphAnomaly().score_nodes(build_graph_sample(nodes, edges))
    assert result.anomalies() == ()


# ---- suspicious subgraph -----------------------------------------
def test_suspicious_subgraph_scores_a_dense_multi_type_cluster_higher() -> None:
    nodes = [
        GraphNode("id1", "Identity", 0.0, 10.0), GraphNode("h1", "Host", 0.0, 10.0),
        GraphNode("ip1", "IpAddress", 0.0, 10.0), GraphNode("d1", "Domain", 0.0, 10.0),
        GraphNode("far", "Host", 0.0, 10.0),
    ]
    edges = [
        GraphEdge("id1", "h1", "AUTHENTICATED_TO", 1.0),
        GraphEdge("h1", "ip1", "CONNECTED_TO", 2.0),
        GraphEdge("ip1", "d1", "RESOLVED", 3.0),
        GraphEdge("id1", "ip1", "CONNECTED_TO", 4.0),
        GraphEdge("h1", "d1", "CONNECTED_TO", 5.0),
    ]
    s = build_graph_sample(nodes, edges)
    h = SuspiciousSubgraphHeuristic()
    dense = h.classify(s, ["id1", "h1", "ip1", "d1"])
    sparse = h.classify(s, ["far", "h1"])
    assert dense.score > sparse.score
    assert 0.0 <= dense.score <= 1.0
    assert h.classify(s, ["id1"]).is_suspicious is False  # < 2 nodes


# ---- threat clustering ------------------------------------------
def _two_triangles() -> object:
    nodes = [GraphNode(x, "Host", 0.0, 10.0) for x in ("a", "b", "c", "x", "y", "z")]
    edges = [
        GraphEdge("a", "b", "CONNECTED_TO", 1.0), GraphEdge("b", "c", "CONNECTED_TO", 1.0),
        GraphEdge("c", "a", "CONNECTED_TO", 1.0),
        GraphEdge("x", "y", "CONNECTED_TO", 1.0), GraphEdge("y", "z", "CONNECTED_TO", 1.0),
        GraphEdge("z", "x", "CONNECTED_TO", 1.0),
    ]
    return build_graph_sample(nodes, edges)


def test_connected_components_finds_two_clusters() -> None:
    res = ConnectedComponentClusterer().cluster(_two_triangles())
    assert len(res.clusters) == 2
    assert {frozenset(c.node_ids) for c in res.clusters} == {
        frozenset(("a", "b", "c")), frozenset(("x", "y", "z"))
    }
    assert all(c.cohesion == 1.0 for c in res.clusters)


def test_label_propagation_is_deterministic() -> None:
    g = _two_triangles()
    a = LabelPropagationClusterer().cluster(g)
    b = LabelPropagationClusterer().cluster(g)
    assert a == b
    assert len(a.clusters) == 2


# ---- registry / GNN boundary ----------------------------------
def test_registry_is_empty_and_load_fails_cleanly_without_artifacts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = GraphModelRegistry(tmp_path / "nonexistent")
    assert reg.available() == []
    with pytest.raises(GraphModelUnavailable):
        reg.load("graphsage")


def test_gnn_forward_needs_torch() -> None:
    from sm_ml.graph.models.gnn import load_torch

    try:
        import torch  # noqa: F401
    except ImportError:
        with pytest.raises(GraphModelUnavailable):
            load_torch()
    else:  # pragma: no cover - torch not installed in CI
        load_torch()
