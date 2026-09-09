"""Threat-cluster discovery — standard library only, deterministic.

- `ConnectedComponentClusterer` — weakly connected components. The safe baseline:
  a cluster is a set of entities that are actually linked.
- `LabelPropagationClusterer` — community detection by synchronous label
  propagation with **sorted, deterministic** tie-breaking and a fixed iteration
  cap (no RNG, so the same graph always yields the same partition).

Both return `ClusterResult` with per-cluster cohesion (internal edge density) and
an overall modularity. No claim is made that a cluster *is* a threat — it is a
group of related entities for an analyst to look at.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..construct import GraphSample
from .base import ClusterResult, ThreatCluster

__all__ = ["ConnectedComponentClusterer", "LabelPropagationClusterer"]

_MAX_ITERS = 50
_MIN_CLUSTER_SIZE = 2


def _undirected_adj(sample: GraphSample) -> list[set[int]]:
    adj: list[set[int]] = [set() for _ in range(sample.num_nodes)]
    for s, d in sample.edge_index:
        if s != d:
            adj[s].add(d)
            adj[d].add(s)
    return adj


def _to_result(sample: GraphSample, labels: list[int], method: str) -> ClusterResult:
    groups: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        groups.setdefault(lab, []).append(i)

    adj = _undirected_adj(sample)
    total_edges = sum(len(a) for a in adj) / 2 or 1.0

    clusters: list[ThreatCluster] = []
    unclustered: list[str] = []
    intra = 0.0
    next_id = 0
    for _, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), min(kv[1]))):
        if len(members) < _MIN_CLUSTER_SIZE:
            unclustered.extend(sample.node_ids[i] for i in members)
            continue
        mset = set(members)
        internal = sum(1 for i in members for j in adj[i] if j in mset) / 2.0
        intra += internal
        possible = len(members) * (len(members) - 1) / 2.0
        cohesion = round(internal / possible, 6) if possible else 0.0
        types = Counter(sample.node_types[i] for i in members)
        clusters.append(ThreatCluster(
            cluster_id=next_id,
            node_ids=tuple(sorted(sample.node_ids[i] for i in members)),
            cohesion=cohesion,
            dominant_node_types=tuple(t for t, _ in types.most_common(3)),
        ))
        next_id += 1

    modularity = round(intra / total_edges, 6)
    return ClusterResult(
        method=method, model_version=None, clusters=tuple(clusters),
        unclustered=tuple(sorted(unclustered)), modularity=modularity, confidence=0.0,
    )


@dataclass(frozen=True)
class ConnectedComponentClusterer:
    method: str = "connected_components"

    def cluster(self, sample: GraphSample) -> ClusterResult:
        adj = _undirected_adj(sample)
        labels = [-1] * sample.num_nodes
        current = 0
        for start in range(sample.num_nodes):
            if labels[start] != -1:
                continue
            stack = [start]
            labels[start] = current
            while stack:
                u = stack.pop()
                for v in sorted(adj[u]):
                    if labels[v] == -1:
                        labels[v] = current
                        stack.append(v)
            current += 1
        return _to_result(sample, labels, self.method)


@dataclass(frozen=True)
class LabelPropagationClusterer:
    method: str = "label_propagation"
    max_iters: int = _MAX_ITERS

    def cluster(self, sample: GraphSample) -> ClusterResult:
        adj = _undirected_adj(sample)
        labels = list(range(sample.num_nodes))
        for _ in range(self.max_iters):
            changed = False
            for u in range(sample.num_nodes):
                if not adj[u]:
                    continue
                counts = Counter(labels[v] for v in adj[u])
                best = min(
                    counts.items(), key=lambda kv: (-kv[1], kv[0])
                )[0]  # most common, lowest label on a tie
                if labels[u] != best:
                    labels[u] = best
                    changed = True
            if not changed:
                break
        # renumber labels to a dense 0..k range, deterministically
        order = {lab: i for i, lab in enumerate(sorted(set(labels)))}
        labels = [order[lab] for lab in labels]
        return _to_result(sample, labels, self.method)
