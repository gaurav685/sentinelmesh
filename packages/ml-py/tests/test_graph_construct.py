from __future__ import annotations

import pytest

from sm_ml.graph import GraphEdge, GraphNode, build_graph_sample, subgraph
from sm_ml.graph.schema import GraphFeatureSchema


def _nodes() -> list[GraphNode]:
    return [
        GraphNode("hub", "Host", first_seen=0.0, last_seen=100.0),
        GraphNode("a", "Identity", first_seen=10.0, last_seen=20.0),
        GraphNode("b", "Identity", first_seen=30.0, last_seen=40.0),
        GraphNode("c", "IpAddress", first_seen=50.0, last_seen=60.0),
    ]


def _edges() -> list[GraphEdge]:
    return [
        GraphEdge("a", "hub", "AUTHENTICATED_TO", 15.0),
        GraphEdge("b", "hub", "AUTHENTICATED_TO", 35.0),
        GraphEdge("hub", "c", "CONNECTED_TO", 55.0),
    ]


def test_sample_shape_and_ordering() -> None:
    s = build_graph_sample(_nodes(), _edges())
    assert s.node_ids == ("a", "b", "c", "hub")  # sorted by node_id
    assert s.num_nodes == 4
    assert s.num_edges == 3
    assert len(s.node_features[0]) == GraphFeatureSchema().node_feature_dim
    assert s.feature_names == GraphFeatureSchema().node_feature_names
    # edge index points into the sorted node list
    assert (s.node_ids[s.edge_index[0][0]], s.node_ids[s.edge_index[0][1]]) == ("a", "hub")


def test_construction_is_deterministic() -> None:
    a = build_graph_sample(_nodes(), _edges())
    b = build_graph_sample(list(reversed(_nodes())), list(reversed(_edges())))
    assert a == b


def test_hub_has_the_highest_total_degree() -> None:
    s = build_graph_sample(_nodes(), _edges())
    names = list(s.feature_names)
    dt = names.index("degree_total")
    by_deg = {nid: row[dt] for nid, row in zip(s.node_ids, s.node_features, strict=True)}
    assert by_deg["hub"] == max(by_deg.values())
    src_only = names.index("is_source_only")
    assert dict(zip(s.node_ids, (r[src_only] for r in s.node_features), strict=True))["a"] == 1.0


def test_temporal_fractions_are_in_0_1() -> None:
    s = build_graph_sample(_nodes(), _edges())
    names = list(s.feature_names)
    for frac in ("age_frac", "activity_span_frac", "recency_frac"):
        col = [row[names.index(frac)] for row in s.node_features]
        assert all(0.0 <= v <= 1.0 for v in col)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda n, e: (n, [*e, GraphEdge("a", "ghost", "X", 1.0)]),  # unknown endpoint
        lambda n, e: ([*n, GraphNode("a", "Host", 0.0, 1.0)], e),   # duplicate id
        lambda n, e: ([], e),                                       # no nodes
    ],
)
def test_malformed_samples_raise(mutate) -> None:  # type: ignore[no-untyped-def]
    n, e = mutate(_nodes(), _edges())
    with pytest.raises(ValueError):
        build_graph_sample(n, e)


def test_node_rejects_inverted_timestamps() -> None:
    with pytest.raises(ValueError):
        GraphNode("x", "Host", first_seen=10.0, last_seen=5.0)


def test_subgraph_recomputes_features_from_its_own_edges() -> None:
    s = build_graph_sample(_nodes(), _edges())
    sub = subgraph(s, ["a", "hub"])
    assert sub.node_ids == ("a", "hub")
    assert sub.num_edges == 1
    with pytest.raises(ValueError):
        subgraph(s, ["a", "missing"])
