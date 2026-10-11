"""Supervised gradient-boosting detector (LightGBM) -- Phase 1.

Unlike every other model in this package, this one is **supervised**: it
needs real attack/benign labels to fit, not just benign traffic. That's a
real, structural difference worth stating plainly rather than blending it
into the "unsupervised anomaly model" framing `AnomalyModel`'s docstring
describes -- `GradientBoostingModel` implements the same `score()` shape
(so the existing benchmark harness can call it identically) but its
`fit()` takes labels, and a benchmark report comparing it against
Isolation Forest/the autoencoder must say so (it's being scored on how well
it learned the train split's own labels, not on density estimation).

Needs `sm-ml[boosting]` (LightGBM); without it `fit`/`load` raise
`ModelUnavailable`, never a fabricated score -- same honest-degradation
shape as `IsolationForestModel`/`AutoencoderModel`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sm_contracts import AnomalyMethod

from .base import AnomalyScore, ModelNotTrained, ModelUnavailable

__all__ = ["GradientBoostingModel"]


def _require_lightgbm() -> Any:
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise ModelUnavailable(f"gradient-boosting deps missing: {exc}") from exc
    return lgb


class GradientBoostingModel:
    method = AnomalyMethod.gradient_boosting

    def __init__(
        self,
        *,
        booster: Any = None,
        feature_names: tuple[str, ...] = (),
        model_version: str | None = None,
        threshold: float = 0.5,
    ) -> None:
        self._booster = booster
        self.feature_names = feature_names
        self.model_version = model_version
        self._threshold = threshold

    @classmethod
    def fit(
        cls,
        feature_names: tuple[str, ...],
        rows: Sequence[Sequence[float]],
        labels: Sequence[int],
        *,
        seed: int,
        model_version: str,
        num_leaves: int = 31,
        n_estimators: int = 200,
        learning_rate: float = 0.05,
        threshold: float = 0.5,
    ) -> GradientBoostingModel:
        """Fit directly on `rows`/`labels` -- real attack labels, not
        benign-only (this is the one model in this package for which that
        would make no sense: a supervised classifier with nothing but one
        class to learn from can't learn a decision boundary at all)."""
        lgb = _require_lightgbm()
        import numpy as np

        if len(rows) != len(labels):
            raise ValueError("rows and labels must be the same length")
        if len(set(labels)) < 2:
            raise ValueError("fit() needs both classes present -- got only one label value")
        dataset = lgb.Dataset(
            np.asarray(rows, dtype=float), label=np.asarray(labels, dtype=float),
            feature_name=list(feature_names),
        )
        params = {
            "objective": "binary", "num_leaves": num_leaves, "learning_rate": learning_rate,
            "seed": seed, "deterministic": True, "verbose": -1,
        }
        booster = lgb.train(params, dataset, num_boost_round=n_estimators)
        return cls(booster=booster, feature_names=feature_names, model_version=model_version, threshold=threshold)

    def save(self, model_dir: Path) -> None:
        if self._booster is None:
            raise ModelNotTrained("nothing to save -- fit() was never called")
        model_dir.mkdir(parents=True, exist_ok=True)
        self._booster.save_model(str(model_dir / "model.txt"))
        metadata = {
            "model_version": self.model_version, "method": "gradient_boosting",
            "feature_names": list(self.feature_names), "threshold": self._threshold,
        }
        (model_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, model_dir: Path) -> GradientBoostingModel:
        lgb = _require_lightgbm()
        artifact = model_dir / "model.txt"
        meta_path = model_dir / "metadata.json"
        if not artifact.exists() or not meta_path.exists():
            raise ModelUnavailable(f"no gradient-boosting artifact under {model_dir}")
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
        try:
            booster = lgb.Booster(model_file=str(artifact))
        except Exception as exc:
            raise ModelUnavailable(f"failed to load {artifact}: {exc}") from exc
        return cls(
            booster=booster, feature_names=tuple(meta["feature_names"]),
            model_version=str(meta["model_version"]), threshold=float(meta["threshold"]),
        )

    def score(self, features: Sequence[float]) -> AnomalyScore:
        if self._booster is None:
            raise ModelNotTrained("gradient-boosting model has not been fit() or load()ed")
        if self.feature_names and len(features) != len(self.feature_names):
            raise ValueError(f"expected {len(self.feature_names)} features, got {len(features)}")
        import numpy as np

        prob = float(self._booster.predict(np.asarray([list(features)], dtype=float))[0])
        return AnomalyScore(
            method=self.method, score=prob, normalized_score=min(1.0, max(0.0, prob)),
            threshold=self._threshold, is_anomaly=prob >= self._threshold,
            model_version=self.model_version, contributing_features=[],
        )
