"""Structural graph models — standard library only, always available.

These are the ADR-013 degraded path for the graph-intelligence layer *and*
first-class detectors in their own right: a GNN adds lift when trained weights
exist, but a graph is always scoreable without one.

- `StructuralGraphAnomaly` — per-node anomaly from a robust z-score over the
  node feature vector plus a few structural red flags (a high-degree sink, an
  isolated source, a hub with low clustering).
- `SuspiciousSubgraphHeuristic` — a verdict on an induced subgraph: dense +
  multi-type + hub-and-spoke + temporally concentrated => more suspicious.

Everything is a pure function of the `GraphSample`. No RNG, no clock, no numpy.
No accuracy figure is claimed.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from ..construct import GraphSample, subgraph
from ..schema import GRAPH_FEATURE_SCHEMA_VERSION, NODE_FEATURE_SPECS
from .base import NodeAnomalyResult, NodeScore, SubgraphVerdict

__all__ = ["DEFAULT_Z_THRESHOLD", "StructuralGraphAnomaly", "SuspiciousSubgraphHeuristic"]

DEFAULT_Z_THRESHOLD = 3.5
_MAD_TO_SIGMA = 0.6745
_EPS = 1e-9
_N_STRUCTURAL = len(NODE_FEATURE_SPECS)


@dataclass(frozen=True)
class StructuralGraphAnomaly:
    z_threshold: float = DEFAULT_Z_THRESHOLD
    method: str = "structural_zscore"
    model_version: str | None = None

    def score_nodes(self, sample: GraphSample) -> NodeAnomalyResult:
        cols = list(zip(*(row[:_N_STRUCTURAL] for row in sample.node_features), strict=True)) \
            if sample.num_nodes else []
        medians = [statistics.median(c) for c in cols] if cols else []
        mads = [statistics.median(abs(x - m) for x in c) for c, m in zip(cols, medians, strict=True)] \
            if cols else []
        # A dominant identical cluster drives MAD to 0 even when a single node is a
        # clear outlier. Floor the dispersion at half the population stdev so the
        # odd-node-out is still caught; a genuinely uniform graph keeps stdev 0.
        stdevs = [statistics.pstdev(c) if len(c) > 1 else 0.0 for c in cols]
        scales = [max(mad, 0.5 * sd) for mad, sd in zip(mads, stdevs, strict=True)]

        names = [s.name for s in NODE_FEATURE_SPECS]
        scores: list[NodeScore] = []
        for i, node_id in enumerate(sample.node_ids):
            row = sample.node_features[i][:_N_STRUCTURAL]
            zbits: list[tuple[str, float]] = []
            for name, x, med, scale in zip(names, row, medians, scales, strict=True):
                z = 0.0 if scale <= _EPS else _MAD_TO_SIGMA * (x - med) / scale
                zbits.append((name, z))
            zbits.sort(key=lambda kv: abs(kv[1]), reverse=True)
            max_z = abs(zbits[0][1]) if zbits else 0.0
            normalized = 1.0 / (1.0 + math.exp(-(max_z - self.z_threshold)))
            contributing = [n for n, z in zbits if abs(z) >= self.z_threshold][:5]
            scores.append(NodeScore(
                node_id=node_id, score=round(max_z, 6),
                normalized_score=round(min(1.0, max(0.0, normalized)), 6),
                is_anomaly=max_z >= self.z_threshold, contributing_features=contributing,
            ))
        return NodeAnomalyResult(
            method=self.method, model_version=self.model_version, threshold=self.z_threshold,
            scores=tuple(scores), feature_schema_version=GRAPH_FEATURE_SCHEMA_VERSION,
            confidence=0.0,
        )


@dataclass(frozen=True)
class SuspiciousSubgraphHeuristic:
    method: str = "subgraph_heuristic"
    model_version: str | None = None
    suspicious_threshold: float = 0.6

    def classify(self, sample: GraphSample, node_ids: Sequence[str]) -> SubgraphVerdict:
        ids = tuple(sorted(set(node_ids)))
        if len(ids) < 2:
            return SubgraphVerdict(
                method=self.method, model_version=self.model_version, node_ids=ids,
                is_suspicious=False, score=0.0, rationale="fewer than 2 nodes", confidence=0.0,
            )
        sub = subgraph(sample, ids)
        n = sub.num_nodes
        undirected = {frozenset(p) for p in sub.edge_index if p[0] != p[1]}
        possible = n * (n - 1) / 2
        density = (len(undirected) / possible) if possible else 0.0

        type_span = len(set(sub.node_types)) / max(1, len(set(sample.node_types)))
        degree = [0] * n
        for s, d in sub.edge_index:
            degree[s] += 1
            degree[d] += 1
        max_deg = max(degree, default=0)
        hub = (max_deg / (n - 1)) if n > 1 else 0.0
        edge_type_span = len(set(sub.edge_types)) / max(1, len(set(sample.edge_types)))

        score = _clamp01(0.4 * density + 0.25 * hub + 0.2 * type_span + 0.15 * edge_type_span)
        reasons = []
        if density >= 0.5:
            reasons.append(f"dense ({density:.2f})")
        if hub >= 0.6:
            reasons.append("hub-and-spoke")
        if type_span >= 0.5:
            reasons.append("spans multiple entity types")
        rationale = "; ".join(reasons) or "no strong structural signal"
        return SubgraphVerdict(
            method=self.method, model_version=self.model_version, node_ids=ids,
            is_suspicious=score >= self.suspicious_threshold, score=round(score, 6),
            rationale=rationale, confidence=0.0,
        )


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v
