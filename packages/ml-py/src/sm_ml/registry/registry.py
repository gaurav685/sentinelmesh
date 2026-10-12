"""Trained-model registry: load anomaly-model artifacts from a directory.

MLflow is the eventual source of truth (ADR-013); for now `ml-training` writes
artifacts under `SM_ML_MODEL_DIR` in this layout:

    <dir>/<name>/<version>/metadata.json
    <dir>/<name>/<version>/model.joblib        (isolation_forest)
    <dir>/<name>/<version>/model.json          (statistical)
    <dir>/<name>/<version>/model.txt           (gradient_boosting)

A missing directory is not an error — `available()` is empty and `load()` raises
`ModelUnavailable`, so `ml-inference` starts and `detection-engine` degrades.

`gradient_boosting` (LightGBM) is gated behind `SM_ML_ENABLE_GRADIENT_BOOSTING`
(real env var, checked once at construction, not a comment) -- a real
`gradient_boosting` artifact under the model directory is simply excluded from
`available()` when the flag is off, so a caller sees exactly the same catalog
as before this model existed and the existing degrade-to-`isolation_forest`
path (ADR-013; `ml-inference`'s `/infer/{model}` -> `MODEL_UNAVAILABLE` ->
caller falls back) needs no new code to keep working.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from sm_contracts import AnomalyMethod

from ..models import (
    AnomalyModel,
    GradientBoostingModel,
    IsolationForestModel,
    ModelUnavailable,
    StatisticalModel,
)

__all__ = ["DEFAULT_MODEL_DIR", "ModelRef", "ModelRegistry"]

DEFAULT_MODEL_DIR = "ml/artifacts"
_ENABLE_GRADIENT_BOOSTING_ENV = "SM_ML_ENABLE_GRADIENT_BOOSTING"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class ModelRef:
    name: str
    version: str
    method: AnomalyMethod
    feature_schema_version: str
    task: str
    path: Path


def _latest_version_dir(model_root: Path) -> Path | None:
    versions = [p for p in model_root.iterdir() if p.is_dir()]
    if not versions:
        return None
    return sorted(versions, key=lambda p: p.name)[-1]


class ModelRegistry:
    def __init__(self, model_dir: str | os.PathLike[str], *, enable_gradient_boosting: bool | None = None) -> None:
        self._dir = Path(model_dir)
        if enable_gradient_boosting is None:
            enable_gradient_boosting = os.environ.get(
                _ENABLE_GRADIENT_BOOSTING_ENV, ""
            ).strip().lower() in _TRUE_VALUES
        self._enable_gradient_boosting = enable_gradient_boosting

    @classmethod
    def from_env(cls) -> ModelRegistry:
        return cls(os.environ.get("SM_ML_MODEL_DIR", DEFAULT_MODEL_DIR))

    def available(self) -> list[ModelRef]:
        if not self._dir.is_dir():
            return []
        refs: list[ModelRef] = []
        for model_root in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            vdir = _latest_version_dir(model_root)
            if vdir is None:
                continue
            meta_path = vdir / "metadata.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            try:
                method = AnomalyMethod(meta["method"])
            except (KeyError, ValueError):
                continue
            if method is AnomalyMethod.gradient_boosting and not self._enable_gradient_boosting:
                continue
            refs.append(
                ModelRef(
                    name=model_root.name,
                    version=str(meta.get("model_version", vdir.name)),
                    method=method,
                    feature_schema_version=str(meta.get("feature_schema_version", "unknown")),
                    task=str(meta.get("task", "anomaly_score")),
                    path=vdir,
                )
            )
        return refs

    def _ref(self, name: str) -> ModelRef:
        for ref in self.available():
            if ref.name == name:
                return ref
        raise ModelUnavailable(f"no registered model named {name!r} under {self._dir}")

    def load(self, name: str) -> AnomalyModel:
        ref = self._ref(name)
        if ref.method is AnomalyMethod.isolation_forest:
            return IsolationForestModel.load(ref.path)
        if ref.method is AnomalyMethod.mad_zscore:
            data = json.loads((ref.path / "model.json").read_text(encoding="utf-8"))
            return StatisticalModel.from_dict(data)
        if ref.method is AnomalyMethod.gradient_boosting:
            return GradientBoostingModel.load(ref.path)
        raise ModelUnavailable(f"registry cannot serve method {ref.method.value!r}")
