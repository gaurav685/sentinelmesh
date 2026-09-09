"""SentinelMesh ML layer — features, preprocessing, anomaly models, registry.

No accuracy / F1 / ROC-AUC / precision / recall / latency / throughput number
appears in this package. Those require a real training + evaluation run
(ADR-024).
"""

from __future__ import annotations

from .features import (
    FEATURE_SCHEMA_VERSION,
    FeatureSchema,
    FeatureVector,
    extract_features,
    schema_for,
)
from .graph import (
    GRAPH_FEATURE_SCHEMA_VERSION,
    ConnectedComponentClusterer,
    GnnNodeAnomalyModel,
    GraphEdge,
    GraphModelRegistry,
    GraphModelUnavailable,
    GraphNode,
    GraphSample,
    LabelPropagationClusterer,
    StructuralGraphAnomaly,
    SuspiciousSubgraphHeuristic,
    build_graph_sample,
)
from .models import (
    AnomalyModel,
    AnomalyScore,
    ModelError,
    ModelNotTrained,
    ModelUnavailable,
    StatisticalModel,
)
from .preprocessing import PREPROCESSING_VERSION, Preprocessor
from .registry import ModelRef, ModelRegistry

__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "GRAPH_FEATURE_SCHEMA_VERSION",
    "PREPROCESSING_VERSION",
    "AnomalyModel",
    "AnomalyScore",
    "ConnectedComponentClusterer",
    "FeatureSchema",
    "FeatureVector",
    "GnnNodeAnomalyModel",
    "GraphEdge",
    "GraphModelRegistry",
    "GraphModelUnavailable",
    "GraphNode",
    "GraphSample",
    "LabelPropagationClusterer",
    "ModelError",
    "ModelNotTrained",
    "ModelRef",
    "ModelRegistry",
    "ModelUnavailable",
    "Preprocessor",
    "StatisticalModel",
    "StructuralGraphAnomaly",
    "SuspiciousSubgraphHeuristic",
    "build_graph_sample",
    "extract_features",
    "schema_for",
]
