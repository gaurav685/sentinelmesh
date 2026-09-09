"""The graph-model interface (Phase 8).

Three tasks, one interface family:

- **node anomaly** — a per-node anomaly score over the sample.
- **suspicious subgraph** — a verdict on an induced subgraph.
- **threat clustering** — a partition of the nodes into clusters.

Every result carries a `model_version` and an explicit `confidence`. Nothing here
claims a model is accurate — that needs an evaluation run (ADR-024,
`ml/models/*/CONTRACT.md`). The always-available implementations
(`StructuralGraphAnomaly`, the clusterers) are deterministic and numpy-free; the
GNN implementations (`sm_ml.graph.models.gnn`) need the optional `sm-ml[gnn]`
dependency and trained weights, and raise `GraphModelUnavailable` /
`GraphModelNotTrained` otherwise — a serving layer degrades to the structural
path, it never fabricates a score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ...errors import ModelError, ModelNotTrained, ModelUnavailable
from ..construct import GraphSample

__all__ = [
    "ClusterResult",
    "GraphAnomalyModel",
    "GraphClusterModel",
    "GraphModelError",
    "GraphModelNotTrained",
    "GraphModelUnavailable",
    "GraphTask",
    "NodeAnomalyResult",
    "NodeScore",
    "SubgraphClassifier",
    "SubgraphVerdict",
    "ThreatCluster",
]

# Reuse the shared model-failure hierarchy so `ml-inference` maps every ML
# failure — flat or graph — to the same typed code.
GraphModelError = ModelError
GraphModelUnavailable = ModelUnavailable
GraphModelNotTrained = ModelNotTrained


class GraphTask(StrEnum):
    node_anomaly = "node_anomaly"
    suspicious_subgraph = "suspicious_subgraph"
    threat_cluster = "threat_cluster"


@dataclass(frozen=True)
class NodeScore:
    node_id: str
    score: float
    """Raw score, higher = more anomalous (method-specific units)."""
    normalized_score: float
    """`score` mapped to [0, 1]."""
    is_anomaly: bool
    contributing_features: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.normalized_score <= 1.0:
            raise ValueError("normalized_score must be in [0, 1]")


@dataclass(frozen=True)
class NodeAnomalyResult:
    method: str
    model_version: str | None
    threshold: float
    scores: tuple[NodeScore, ...]
    feature_schema_version: str
    confidence: float = 0.0

    def anomalies(self) -> tuple[NodeScore, ...]:
        return tuple(s for s in self.scores if s.is_anomaly)


@dataclass(frozen=True)
class SubgraphVerdict:
    method: str
    model_version: str | None
    node_ids: tuple[str, ...]
    is_suspicious: bool
    score: float
    """[0, 1] — likelihood the subgraph is a coordinated pattern, never a certainty."""
    rationale: str
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in [0, 1]")


@dataclass(frozen=True)
class ThreatCluster:
    cluster_id: int
    node_ids: tuple[str, ...]
    cohesion: float
    """[0, 1] — internal edge density of the cluster."""
    dominant_node_types: tuple[str, ...]


@dataclass(frozen=True)
class ClusterResult:
    method: str
    model_version: str | None
    clusters: tuple[ThreatCluster, ...]
    unclustered: tuple[str, ...]
    modularity: float
    confidence: float = 0.0


@runtime_checkable
class GraphAnomalyModel(Protocol):
    @property
    def method(self) -> str: ...

    @property
    def model_version(self) -> str | None: ...

    def score_nodes(self, sample: GraphSample) -> NodeAnomalyResult: ...


@runtime_checkable
class SubgraphClassifier(Protocol):
    @property
    def method(self) -> str: ...

    def classify(self, sample: GraphSample, node_ids: Sequence[str]) -> SubgraphVerdict: ...


@runtime_checkable
class GraphClusterModel(Protocol):
    @property
    def method(self) -> str: ...

    def cluster(self, sample: GraphSample) -> ClusterResult: ...
