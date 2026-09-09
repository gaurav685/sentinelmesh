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
    "PREPROCESSING_VERSION",
    "AnomalyModel",
    "AnomalyScore",
    "FeatureSchema",
    "FeatureVector",
    "ModelError",
    "ModelNotTrained",
    "ModelRef",
    "ModelRegistry",
    "ModelUnavailable",
    "Preprocessor",
    "StatisticalModel",
    "extract_features",
    "schema_for",
]
