"""Versioned graph feature + output schemas (Phase 8; `ml/features/graph.md`).

A `GraphFeatureSchema` is a **contract**: an ordered list of named, bounded float
features computed for every node of a graph sample. Bump
`GRAPH_FEATURE_SCHEMA_VERSION` on any change to the feature set or ordering — a
GNN trained on v1 cannot consume v2. Every graph model artifact and every
`GraphModelOutput` records the version it used.

No accuracy / AUC / precision / recall number appears anywhere in this package
(ADR-024) — those need a real training + evaluation run.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..features.schema import FeatureSpec

__all__ = [
    "GRAPH_FEATURE_SCHEMA_VERSION",
    "GRAPH_NODE_TYPES",
    "GRAPH_OUTPUT_SCHEMA_VERSION",
    "NODE_FEATURE_SPECS",
    "GraphFeatureSchema",
    "node_type_index",
]

GRAPH_FEATURE_SCHEMA_VERSION = "1"
GRAPH_OUTPUT_SCHEMA_VERSION = "1"

# The node-label vocabulary a graph sample can carry. Mirrors
# `sm_contracts.GRAPH_NODE_LABELS` but stays a plain tuple here so `sm_ml` keeps
# no dependency on the graph-command contract. Order is the categorical index.
GRAPH_NODE_TYPES: tuple[str, ...] = (
    "Identity", "Host", "IpAddress", "Domain", "Process", "File", "Sensor",
    "Detection", "AttackChain", "AttackTechnique", "ThreatActor", "Campaign",
)


def node_type_index(node_type: str) -> int:
    """Categorical index of a node type; unknown types map to `len(GRAPH_NODE_TYPES)`."""
    try:
        return GRAPH_NODE_TYPES.index(node_type)
    except ValueError:
        return len(GRAPH_NODE_TYPES)


def _s(name: str, lo: float, hi: float, description: str) -> FeatureSpec:
    return FeatureSpec(name=name, lo=lo, hi=hi, description=description)


# Ordered node feature vector. Structural features come from the edge set of the
# sample; temporal features from the node's first/last-seen timestamps relative
# to the sample window. All are deterministic and numpy-free.
NODE_FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    _s("degree_in", 0.0, 1.0, "in-degree, log-scaled and normalised by the sample max"),
    _s("degree_out", 0.0, 1.0, "out-degree, log-scaled and normalised"),
    _s("degree_total", 0.0, 1.0, "total degree, log-scaled and normalised"),
    _s("unique_neighbors", 0.0, 1.0, "distinct neighbours, log-scaled and normalised"),
    _s("self_loops", 0.0, 1.0, "1.0 if the node has a self-loop"),
    _s("edge_type_diversity", 0.0, 1.0, "distinct incident edge types / total edge types"),
    _s("clustering_coeff", 0.0, 1.0, "local clustering coefficient (triangles / possible)"),
    _s("is_source_only", 0.0, 1.0, "1.0 if the node has out-edges but no in-edges"),
    _s("is_sink_only", 0.0, 1.0, "1.0 if the node has in-edges but no out-edges"),
    _s("age_frac", 0.0, 1.0, "(first_seen - window_start) / window_span"),
    _s("activity_span_frac", 0.0, 1.0, "(last_seen - first_seen) / window_span"),
    _s("recency_frac", 0.0, 1.0, "(last_seen - window_start) / window_span"),
)

_TYPE_ONEHOT_LEN = len(GRAPH_NODE_TYPES) + 1  # + 1 for "unknown"


@dataclass(frozen=True)
class GraphFeatureSchema:
    version: str = GRAPH_FEATURE_SCHEMA_VERSION

    @property
    def node_feature_names(self) -> tuple[str, ...]:
        base = tuple(s.name for s in NODE_FEATURE_SPECS)
        onehot = tuple(f"type_{t}" for t in (*GRAPH_NODE_TYPES, "unknown"))
        return base + onehot

    @property
    def node_feature_dim(self) -> int:
        return len(NODE_FEATURE_SPECS) + _TYPE_ONEHOT_LEN
