"""SentinelMesh graph-intelligence layer (Phase 8).

    graph nodes + edges
      -> GraphSample (deterministic, numpy-free feature matrix + edge index)
      -> { node anomaly | suspicious subgraph | threat cluster }

The structural models are standard-library and always available (the ADR-013
degraded path). The GNN models (`GnnNodeAnomalyModel`, GraphSAGE / GAT) need the
optional `sm-ml[gnn]` dependency and trained weights; without either they raise a
typed `GraphModel*` error and a serving layer falls back to the structural path —
no score is ever fabricated.

No accuracy / AUC / precision / recall number appears in this subpackage
(ADR-024). `ml/models/{graphsage,gat,graph_anomaly}/CONTRACT.md` carry the
literal `METRICS: NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION`.
"""

from __future__ import annotations

from .construct import GraphEdge, GraphNode, GraphSample, build_graph_sample, subgraph
from .models import (
    ClusterResult,
    ConnectedComponentClusterer,
    GNNArchitectureSpec,
    GnnNodeAnomalyModel,
    GraphModelError,
    GraphModelNotTrained,
    GraphModelUnavailable,
    GraphTask,
    LabelPropagationClusterer,
    NodeAnomalyResult,
    NodeScore,
    StructuralGraphAnomaly,
    SubgraphVerdict,
    SuspiciousSubgraphHeuristic,
    ThreatCluster,
)
from .registry import DEFAULT_GRAPH_MODEL_DIR, GraphModelRef, GraphModelRegistry
from .schema import (
    GRAPH_FEATURE_SCHEMA_VERSION,
    GRAPH_NODE_TYPES,
    GRAPH_OUTPUT_SCHEMA_VERSION,
    GraphFeatureSchema,
)

__all__ = [
    "DEFAULT_GRAPH_MODEL_DIR",
    "GRAPH_FEATURE_SCHEMA_VERSION",
    "GRAPH_NODE_TYPES",
    "GRAPH_OUTPUT_SCHEMA_VERSION",
    "ClusterResult",
    "ConnectedComponentClusterer",
    "GNNArchitectureSpec",
    "GnnNodeAnomalyModel",
    "GraphEdge",
    "GraphFeatureSchema",
    "GraphModelError",
    "GraphModelNotTrained",
    "GraphModelRef",
    "GraphModelRegistry",
    "GraphModelUnavailable",
    "GraphNode",
    "GraphSample",
    "GraphTask",
    "LabelPropagationClusterer",
    "NodeAnomalyResult",
    "NodeScore",
    "StructuralGraphAnomaly",
    "SubgraphVerdict",
    "SuspiciousSubgraphHeuristic",
    "ThreatCluster",
    "build_graph_sample",
    "subgraph",
]
