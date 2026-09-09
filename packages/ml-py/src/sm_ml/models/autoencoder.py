"""Autoencoder anomaly model — architecture specified, not trained.

An autoencoder is justified for the higher-dimensional feature groups
(network-flow, process-exec) where a single reconstruction error captures
correlated deviations a per-feature z-score misses. The architecture is fixed
here so `ml-training` and `ml-inference` agree; **there is no trained artifact**,
so `score` raises `ModelNotTrained`. Performance is
`NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION` (see
`ml/models/autoencoder/CONTRACT.md`).

Reference architecture (to be built with PyTorch in `ml-training`):

    input(d) -> Linear(d, h1) -> ReLU
              -> Linear(h1, h2) -> ReLU        (bottleneck = h2, h2 < h1 < d)
              -> Linear(h2, h1) -> ReLU
              -> Linear(h1, d)                 (reconstruction)

    anomaly score  = mean squared reconstruction error
    threshold      = a high quantile (default p99) of the training-set error
    normalisation  = error / (threshold * k), clamped to [0, 1]
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sm_contracts import AnomalyMethod

from .base import AnomalyScore, ModelNotTrained

__all__ = ["AutoencoderModel", "AutoencoderSpec"]


@dataclass(frozen=True)
class AutoencoderSpec:
    input_dim: int
    hidden_dims: tuple[int, ...] = (16, 8)
    activation: str = "relu"
    error_quantile: float = 0.99
    normalisation_k: float = 2.0

    def __post_init__(self) -> None:
        if self.input_dim <= 0:
            raise ValueError("input_dim must be positive")
        if any(h <= 0 for h in self.hidden_dims):
            raise ValueError("hidden_dims must be positive")
        if list(self.hidden_dims) != sorted(self.hidden_dims, reverse=True):
            raise ValueError("hidden_dims must be strictly decreasing to the bottleneck")


class AutoencoderModel:
    method = AnomalyMethod.autoencoder

    def __init__(self, spec: AutoencoderSpec) -> None:
        self.spec = spec
        self.model_version: str | None = None

    def score(self, features: Sequence[float]) -> AnomalyScore:
        raise ModelNotTrained(
            "the autoencoder has no trained artifact — run ml-training against a "
            "dataset first (ml/models/autoencoder/CONTRACT.md)"
        )
