"""Trained-model registry: load anomaly-model artifacts from a directory.

MLflow is the eventual source of truth (ADR-013); for now `ml-training` writes
artifacts under `SM_ML_MODEL_DIR` in this layout:

    <dir>/<name>/<version>/metadata.json
    <dir>/<name>/<version>/model.joblib        (isolation_forest)
    <dir>/<name>/<version>/model.json          (statistical)

A missing directory is not an error — `available()` is empty and `load()` raises
`ModelUnavailable`, so `ml-inference` starts and `detection-engine` degrades.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from sm_contracts import AnomalyMethod

from ..models import (
    AnomalyModel,
    IsolationForestModel,
    ModelUnavailable,
    StatisticalModel,
)

__all__ = ["DEFAULT_MODEL_DIR", "ModelRef", "ModelRegistry"]

DEFAULT_MODEL_DIR = "ml/artifacts"


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
    def __init__(self, model_dir: str | os.PathLike[str]) -> None:
        self._dir = Path(model_dir)

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
        raise ModelUnavailable(f"registry cannot serve method {ref.method.value!r}")
