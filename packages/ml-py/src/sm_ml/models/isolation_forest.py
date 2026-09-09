"""Isolation Forest anomaly model (scikit-learn).

Needs `sm-ml[serving]` (numpy + scikit-learn + joblib) *and* a trained artifact.
Without either, `load` raises `ModelUnavailable` and the caller degrades — it
never fabricates a score.

Artifact layout (written by `ml-training`):

    <dir>/model.joblib      # a fitted sklearn.ensemble.IsolationForest
    <dir>/metadata.json     # { model_version, feature_names, feature_schema_version,
                            #   score_min, score_max, threshold }

Score: `-estimator.score_samples(x)` (higher = more anomalous), then min-max
normalised into [0, 1] with the training-set bounds from the metadata.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sm_contracts import AnomalyMethod

from .base import AnomalyScore, ModelUnavailable

__all__ = ["IsolationForestModel"]


def _require_serving() -> Any:
    try:
        import joblib  # noqa: F401
        import numpy as np

        return np
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ModelUnavailable(f"isolation-forest serving deps missing: {exc}") from exc


class IsolationForestModel:
    method = AnomalyMethod.isolation_forest

    def __init__(
        self,
        estimator: Any,
        *,
        feature_names: tuple[str, ...],
        model_version: str,
        score_min: float,
        score_max: float,
        threshold: float,
    ) -> None:
        self._estimator = estimator
        self.feature_names = feature_names
        self.model_version: str | None = model_version
        self._lo = score_min
        self._hi = score_max
        self._threshold = threshold

    @classmethod
    def load(cls, model_dir: Path) -> IsolationForestModel:
        np = _require_serving()
        import joblib

        artifact = model_dir / "model.joblib"
        meta_path = model_dir / "metadata.json"
        if not artifact.exists() or not meta_path.exists():
            raise ModelUnavailable(f"no isolation-forest artifact under {model_dir}")
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
        try:
            estimator = joblib.load(artifact)
        except Exception as exc:
            raise ModelUnavailable(f"failed to load {artifact}: {exc}") from exc
        _ = np  # numpy is imported so the estimator's predict path has it
        return cls(
            estimator,
            feature_names=tuple(meta["feature_names"]),
            model_version=str(meta["model_version"]),
            score_min=float(meta["score_min"]),
            score_max=float(meta["score_max"]),
            threshold=float(meta["threshold"]),
        )

    def score(self, features: Sequence[float]) -> AnomalyScore:
        np = _require_serving()
        if len(features) != len(self.feature_names):
            raise ValueError(
                f"expected {len(self.feature_names)} features, got {len(features)}"
            )
        raw = float(-self._estimator.score_samples(np.asarray([list(features)], dtype=float))[0])
        span = self._hi - self._lo
        normalized = (raw - self._lo) / span if span > 1e-9 else 0.0
        normalized = min(1.0, max(0.0, normalized))
        return AnomalyScore(
            method=self.method,
            score=raw,
            normalized_score=normalized,
            threshold=self._threshold,
            is_anomaly=raw >= self._threshold,
            model_version=self.model_version,
            contributing_features=[],
        )
