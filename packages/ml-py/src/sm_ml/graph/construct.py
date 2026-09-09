"""Deterministic graph construction: nodes + edges -> a `GraphSample`.

The sample is numpy-free and torch-free — a plain matrix of node features and an
edge index. A torch-geometric adapter (`sm_ml.graph.models.gnn`) converts it when
that optional dependency is installed.

Determinism (Constitution §3): nodes are ordered by `node_id`, features are pure
functions of the graph and the sample window, no clock and no RNG. A malformed
sample (an edge referencing an unknown node, a non-finite feature) raises
`ValueError` — it is never silently repaired.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .schema import (
    GRAPH_FEATURE_SCHEMA_VERSION,
    GRAPH_NODE_TYPES,
    NODE_FEATURE_SPECS,
    node_type_index,
)

__all__ = ["GraphEdge", "GraphNode", "GraphSample", "build_graph_sample", "subgraph"]


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    first_seen: float  # epoch seconds
    last_seen: float

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("node_id must be non-empty")
        if self.last_seen < self.first_seen:
            raise ValueError(f"node {self.node_id}: last_seen < first_seen")


@dataclass(frozen=True)
class GraphEdge:
    src_id: str
    dst_id: str
    edge_type: str
    observed_at: float

    def __post_init__(self) -> None:
        if not (self.src_id and self.dst_id and self.edge_type):
            raise ValueError("edge needs src_id, dst_id and edge_type")


@dataclass(frozen=True)
class GraphSample:
    """One graph, ready for a model. `node_features[i]` is the feature row for
    `node_ids[i]`; `edge_index` holds `(src_idx, dst_idx)` pairs into `node_ids`."""

    schema_version: str
    node_ids: tuple[str, ...]
    node_types: tuple[str, ...]
    node_features: tuple[tuple[float, ...], ...]
    edge_index: tuple[tuple[int, int], ...]
    edge_types: tuple[str, ...]
    window_start: float
    window_end: float
    feature_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def num_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def num_edges(self) -> int:
        return len(self.edge_index)

    def index_of(self, node_id: str) -> int:
        return self.node_ids.index(node_id)


def _norm_log(value: float, max_value: float) -> float:
    if max_value <= 0.0:
        return 0.0
    return min(1.0, math.log1p(max(0.0, value)) / math.log1p(max_value))


def build_graph_sample(
    nodes: Iterable[GraphNode],
    edges: Iterable[GraphEdge],
    *,
    window_start: float | None = None,
    window_end: float | None = None,
) -> GraphSample:
    node_list = sorted(nodes, key=lambda n: n.node_id)
    if not node_list:
        raise ValueError("a graph sample needs at least one node")
    ids = [n.node_id for n in node_list]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate node_id in the sample")
    idx = {nid: i for i, nid in enumerate(ids)}

    # Sort edges so the sample (and therefore any model output) is deterministic
    # regardless of the order events arrived in.
    edge_list = sorted(edges, key=lambda e: (e.src_id, e.dst_id, e.edge_type, e.observed_at))
    for e in edge_list:
        if e.src_id not in idx or e.dst_id not in idx:
            raise ValueError(f"edge {e.src_id}->{e.dst_id} references an unknown node")

    w_start = window_start if window_start is not None else min(n.first_seen for n in node_list)
    w_end = window_end if window_end is not None else max(n.last_seen for n in node_list)
    span = max(1e-9, w_end - w_start)

    all_edge_types = sorted({e.edge_type for e in edge_list})
    n_edge_types = max(1, len(all_edge_types))

    # adjacency
    out_deg = [0] * len(ids)
    in_deg = [0] * len(ids)
    self_loop = [0.0] * len(ids)
    neighbors: list[set[int]] = [set() for _ in ids]
    incident_types: list[set[str]] = [set() for _ in ids]
    adj: list[set[int]] = [set() for _ in ids]
    for e in edge_list:
        s, d = idx[e.src_id], idx[e.dst_id]
        out_deg[s] += 1
        in_deg[d] += 1
        incident_types[s].add(e.edge_type)
        incident_types[d].add(e.edge_type)
        if s == d:
            self_loop[s] = 1.0
        else:
            neighbors[s].add(d)
            neighbors[d].add(s)
            adj[s].add(d)
            adj[d].add(s)

    max_in = max(in_deg, default=0)
    max_out = max(out_deg, default=0)
    max_tot = max((a + b for a, b in zip(in_deg, out_deg, strict=True)), default=0)
    max_nbr = max((len(n) for n in neighbors), default=0)

    rows: list[tuple[float, ...]] = []
    for i, node in enumerate(node_list):
        tot = in_deg[i] + out_deg[i]
        nbr = adj[i]
        possible = len(nbr) * (len(nbr) - 1)
        triangles = sum(1 for u in nbr for v in nbr if u != v and v in adj[u])
        clustering = (triangles / possible) if possible else 0.0
        structural = (
            _norm_log(in_deg[i], max_in),
            _norm_log(out_deg[i], max_out),
            _norm_log(tot, max_tot),
            _norm_log(len(neighbors[i]), max_nbr),
            self_loop[i],
            min(1.0, len(incident_types[i]) / n_edge_types),
            min(1.0, clustering),
            1.0 if (out_deg[i] > 0 and in_deg[i] == 0) else 0.0,
            1.0 if (in_deg[i] > 0 and out_deg[i] == 0) else 0.0,
            _clamp01((node.first_seen - w_start) / span),
            _clamp01((node.last_seen - node.first_seen) / span),
            _clamp01((node.last_seen - w_start) / span),
        )
        if len(structural) != len(NODE_FEATURE_SPECS):  # pragma: no cover - guards a schema edit
            raise ValueError("structural feature count drifted from NODE_FEATURE_SPECS")
        onehot = [0.0] * (len(GRAPH_NODE_TYPES) + 1)
        onehot[node_type_index(node.node_type)] = 1.0
        row = (*structural, *onehot)
        if any(not math.isfinite(v) for v in row):
            raise ValueError(f"node {node.node_id}: non-finite feature value")
        rows.append(row)

    names = tuple(s.name for s in NODE_FEATURE_SPECS) + tuple(
        f"type_{t}" for t in (*GRAPH_NODE_TYPES, "unknown")
    )
    return GraphSample(
        schema_version=GRAPH_FEATURE_SCHEMA_VERSION,
        node_ids=tuple(ids),
        node_types=tuple(n.node_type for n in node_list),
        node_features=tuple(rows),
        edge_index=tuple((idx[e.src_id], idx[e.dst_id]) for e in edge_list),
        edge_types=tuple(e.edge_type for e in edge_list),
        window_start=w_start,
        window_end=w_end,
        feature_names=names,
    )


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def subgraph(sample: GraphSample, node_ids: Sequence[str]) -> GraphSample:
    """The induced subgraph over `node_ids` — features are **recomputed** from
    the subgraph's own edge set, never sliced from the parent."""
    keep = set(node_ids)
    missing = keep - set(sample.node_ids)
    if missing:
        raise ValueError(f"subgraph node(s) not in the sample: {sorted(missing)}")
    nodes = [
        GraphNode(nid, sample.node_types[sample.index_of(nid)], sample.window_start, sample.window_end)
        for nid in sorted(keep)
    ]
    edges = [
        GraphEdge(sample.node_ids[s], sample.node_ids[d], et, sample.window_end)
        for (s, d), et in zip(sample.edge_index, sample.edge_types, strict=True)
        if sample.node_ids[s] in keep and sample.node_ids[d] in keep
    ]
    return build_graph_sample(
        nodes, edges, window_start=sample.window_start, window_end=sample.window_end
    )
