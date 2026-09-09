"""Graph intelligence over a live neighbourhood (Phase 8).

Take a bounded, tenant-scoped `GraphView` (from `GraphRepository.neighbors`) and
run the always-available `sm_ml.graph` structural models on it:

- per-node structural anomaly (`StructuralGraphAnomaly`),
- threat-cluster discovery (`LabelPropagationClusterer`),
- a suspicious-subgraph verdict over the whole neighbourhood.

No GNN is called here — the structural path is stdlib and deterministic. A caller
that wants the GNN score calls `ml-inference` `POST /api/v1/infer/graph/{model}`
and degrades to this when the model is unavailable.

Node timestamps in the graph are stored as ISO strings or absent; when an epoch
value is not available the temporal node features are neutral (0). The structural
features (degree, clustering, source/sink) do not depend on them.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_ml.graph import (
    GRAPH_FEATURE_SCHEMA_VERSION,
    GraphEdge,
    GraphNode,
    LabelPropagationClusterer,
    StructuralGraphAnomaly,
    SuspiciousSubgraphHeuristic,
    build_graph_sample,
)

from .repository import GraphView

__all__ = ["ClusterFinding", "GraphIntel", "NodeAnomalyFinding", "analyse_neighbourhood"]


@dataclass(frozen=True)
class NodeAnomalyFinding:
    node_id: str
    node_type: str
    normalized_score: float
    contributing_features: list[str]


@dataclass(frozen=True)
class ClusterFinding:
    cluster_id: int
    size: int
    cohesion: float
    node_types: list[str]


@dataclass(frozen=True)
class GraphIntel:
    subject_label: str
    subject_key: str
    feature_schema_version: str
    node_count: int
    edge_count: int
    truncated: bool
    anomalies: list[NodeAnomalyFinding]
    clusters: list[ClusterFinding]
    subgraph_suspicious: bool
    subgraph_score: float
    subgraph_rationale: str
    methods: dict[str, str]


def _epoch(props: dict[str, object], key: str, default: float) -> float:
    v = props.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    return default


def analyse_neighbourhood(
    view: GraphView, *, label: str, key: str, z_threshold: float
) -> GraphIntel:
    if not view.nodes:
        raise ValueError("empty neighbourhood")

    node_ids = {n.id for n in view.nodes}
    nodes = [
        GraphNode(
            node_id=n.id,
            node_type=(n.labels[0] if n.labels else "unknown"),
            first_seen=_epoch(n.properties, "first_seen_epoch", 0.0),
            last_seen=_epoch(n.properties, "last_seen_epoch", 1.0),
        )
        for n in view.nodes
    ]
    edges = [
        GraphEdge(e.src, e.dst, e.type, _epoch(e.properties, "last_seen_epoch", 1.0))
        for e in view.edges
        if e.src in node_ids and e.dst in node_ids
    ]
    sample = build_graph_sample(nodes, edges)

    anom = StructuralGraphAnomaly(z_threshold=z_threshold).score_nodes(sample)
    type_by_id = dict(zip(sample.node_ids, sample.node_types, strict=True))
    anomalies = [
        NodeAnomalyFinding(
            node_id=s.node_id, node_type=type_by_id[s.node_id],
            normalized_score=s.normalized_score, contributing_features=s.contributing_features,
        )
        for s in anom.anomalies()
    ]

    clustering = LabelPropagationClusterer().cluster(sample)
    clusters = [
        ClusterFinding(
            cluster_id=c.cluster_id, size=len(c.node_ids), cohesion=c.cohesion,
            node_types=list(c.dominant_node_types),
        )
        for c in clustering.clusters
    ]

    verdict = SuspiciousSubgraphHeuristic().classify(sample, list(sample.node_ids))

    return GraphIntel(
        subject_label=label, subject_key=key,
        feature_schema_version=GRAPH_FEATURE_SCHEMA_VERSION,
        node_count=sample.num_nodes, edge_count=sample.num_edges, truncated=view.truncated,
        anomalies=anomalies, clusters=clusters,
        subgraph_suspicious=verdict.is_suspicious, subgraph_score=verdict.score,
        subgraph_rationale=verdict.rationale,
        methods={
            "anomaly": anom.method, "clustering": clustering.method,
            "subgraph": verdict.method,
        },
    )
