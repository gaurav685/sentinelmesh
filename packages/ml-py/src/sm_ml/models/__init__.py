"""Anomaly models: the interface, the always-available statistical detector, and
the trained-model wrappers (Isolation Forest, autoencoder)."""

from __future__ import annotations

from .autoencoder import AutoencoderModel, AutoencoderSpec
from .base import (
    AnomalyModel,
    AnomalyScore,
    ModelError,
    ModelNotTrained,
    ModelUnavailable,
)
from .gradient_boosting import GradientBoostingModel
from .isolation_forest import IsolationForestModel
from .statistical import DEFAULT_Z_THRESHOLD, StatisticalModel

__all__ = [
    "DEFAULT_Z_THRESHOLD",
    "AnomalyModel",
    "AnomalyScore",
    "AutoencoderModel",
    "AutoencoderSpec",
    "GradientBoostingModel",
    "IsolationForestModel",
    "ModelError",
    "ModelNotTrained",
    "ModelUnavailable",
    "StatisticalModel",
]
