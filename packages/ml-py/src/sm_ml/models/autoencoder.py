"""Autoencoder anomaly model.

An autoencoder is justified for the higher-dimensional feature groups
(network-flow, process-exec) where a single reconstruction error captures
correlated deviations a per-feature z-score misses.

Reference architecture (built with PyTorch; `sm-ml[autoencoder]`, optional —
`torch` is not installed in CI; without it `load`/`score` raise
`ModelUnavailable`, never a fabricated score):

    input(d) -> Linear(d, h1) -> ReLU
              -> Linear(h1, h2) -> ReLU        (bottleneck = h2, h2 < h1 < d)
              -> Linear(h2, h1) -> ReLU
              -> Linear(h1, d)                 (reconstruction)

    anomaly score  = mean squared reconstruction error
    threshold      = a high quantile (default p99) of the training-set error
    normalisation  = error / (threshold * k), clamped to [0, 1]

`AutoencoderModel()` with no checkpoint raises `ModelNotTrained` on `score` —
the pre-training behaviour is unchanged and is still what `ml-inference`
sees until a real checkpoint exists. `AutoencoderModel.load(model_dir)`
loads a real trained checkpoint produced by `ml-training`
(`scripts/train_autoencoder_network_flow.py`) and scores via a genuine
forward pass — exactly the same honest-degradation shape as
`sm_ml.models.isolation_forest.IsolationForestModel.load` and
`sm_ml.graph.models.gnn`'s checkpoint loading.

Artifact layout (written by `ml-training`):

    <dir>/model.pt          # torch.save of the trained nn.Module (whole module,
                            # not just a state_dict, so `ml-inference` never has
                            # to reconstruct the architecture by hand)
    <dir>/metadata.json     # { model_version, feature_names, feature_schema_version,
                            #   hidden_dims, error_threshold, normalisation_k }
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sm_contracts import AnomalyMethod

from .base import AnomalyScore, ModelNotTrained, ModelUnavailable

__all__ = ["AutoencoderModel", "AutoencoderSpec", "build_module"]

_AutoencoderModule: Any = None  # populated by `_autoencoder_class()` on first use


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


def _require_torch() -> Any:
    try:
        import torch

        return torch
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ModelUnavailable(f"autoencoder serving deps missing: {exc}") from exc


def _autoencoder_class() -> Any:
    """The `nn.Module` class, defined at module scope (not inside a closure)
    so `torch.save`/`torch.load` of a whole module instance can pickle it --
    a local class cannot be pickled, which `torch.save` only discovers when
    actually called, not at class-definition time."""
    torch = _require_torch()
    from torch import nn

    global _AutoencoderModule
    if _AutoencoderModule is not None:
        return _AutoencoderModule

    class _Module(nn.Module):
        def __init__(self, dims: list[int]) -> None:
            super().__init__()
            encoder_layers: list[Any] = []
            for i in range(len(dims) - 1):
                encoder_layers.append(nn.Linear(dims[i], dims[i + 1]))
                encoder_layers.append(nn.ReLU())
            decoder_dims = list(reversed(dims))
            decoder_layers: list[Any] = []
            for i in range(len(decoder_dims) - 1):
                decoder_layers.append(nn.Linear(decoder_dims[i], decoder_dims[i + 1]))
                if i < len(decoder_dims) - 2:
                    decoder_layers.append(nn.ReLU())
            self.encoder = nn.Sequential(*encoder_layers)
            self.decoder = nn.Sequential(*decoder_layers)

        def forward(self, x: Any) -> Any:
            return self.decoder(self.encoder(x))

    # `torch.save`/`load` of a whole module pickles by `__module__` +
    # `__qualname__`; a class defined inside this function has a
    # `<locals>`-qualified name pickle cannot re-resolve even after the
    # `global` assignment below puts it in this module's namespace, so the
    # qualname is corrected to match where it actually now lives.
    _Module.__qualname__ = _Module.__name__ = "_AutoencoderModule"
    _AutoencoderModule = _Module
    _ = torch
    return _AutoencoderModule


def build_module(spec: AutoencoderSpec) -> Any:
    """Build the encoder/decoder `nn.Module` described in this module's
    docstring. Shared by `ml-training` (fits the weights) and this module
    (loads them) so the two can never silently disagree on architecture."""
    cls = _autoencoder_class()
    return cls([spec.input_dim, *spec.hidden_dims])


class AutoencoderModel:
    method = AnomalyMethod.autoencoder

    def __init__(
        self,
        spec: AutoencoderSpec,
        *,
        module: Any = None,
        feature_names: tuple[str, ...] = (),
        model_version: str | None = None,
        error_threshold: float = 0.0,
    ) -> None:
        self.spec = spec
        self._module = module
        self.feature_names = feature_names
        self.model_version = model_version
        self._threshold = error_threshold

    @classmethod
    def load(cls, model_dir: Path) -> AutoencoderModel:
        torch = _require_torch()
        _autoencoder_class()  # registers `_AutoencoderModule` so the unpickler below can find it
        artifact = model_dir / "model.pt"
        meta_path = model_dir / "metadata.json"
        if not artifact.exists() or not meta_path.exists():
            raise ModelUnavailable(f"no autoencoder artifact under {model_dir}")
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
        try:
            module = torch.load(artifact, map_location="cpu", weights_only=False)
            module.eval()
        except Exception as exc:
            raise ModelUnavailable(f"failed to load {artifact}: {exc}") from exc
        spec = AutoencoderSpec(
            input_dim=int(meta["input_dim"]),
            hidden_dims=tuple(meta["hidden_dims"]),
            error_quantile=float(meta["error_quantile"]),
            normalisation_k=float(meta["normalisation_k"]),
        )
        return cls(
            spec,
            module=module,
            feature_names=tuple(meta["feature_names"]),
            model_version=str(meta["model_version"]),
            error_threshold=float(meta["error_threshold"]),
        )

    def score(self, features: Sequence[float]) -> AnomalyScore:
        if self._module is None:
            raise ModelNotTrained(
                "the autoencoder has no trained artifact — run ml-training against a "
                "dataset first (ml/models/autoencoder/CONTRACT.md), or load one with "
                "AutoencoderModel.load(model_dir)"
            )
        torch = _require_torch()
        if self.feature_names and len(features) != len(self.feature_names):
            raise ValueError(f"expected {len(self.feature_names)} features, got {len(features)}")
        x = torch.tensor([list(features)], dtype=torch.float32)
        with torch.no_grad():
            recon = self._module(x)
            err = float(torch.mean((recon - x) ** 2).item())
        normalized = min(1.0, max(0.0, err / (self._threshold * self.spec.normalisation_k)))
        return AnomalyScore(
            method=self.method,
            score=err,
            normalized_score=normalized,
            threshold=self._threshold,
            is_anomaly=err >= self._threshold,
            model_version=self.model_version,
            contributing_features=[],
        )
