"""Graph-model registry — load GNN checkpoints from a directory.

Layout (written by `ml-training`):

    $SM_ML_GRAPH_MODEL_DIR/<name>/<version>/metadata.json
    $SM_ML_GRAPH_MODEL_DIR/<name>/<version>/model.pt          (torch checkpoint)

A missing directory is not an error — `available()` is empty and `load()` raises
`GraphModelUnavailable`, so `ml-inference` starts and any graph-intelligence
consumer degrades to `sm_ml.graph.models.structural`. No metric is read or
claimed from `metadata.json` beyond what a real evaluation run wrote.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .models.base import GraphModelUnavailable
from .models.gnn import GAT_SPEC, GRAPHSAGE_SPEC, GnnNodeAnomalyModel

__all__ = ["DEFAULT_GRAPH_MODEL_DIR", "GraphModelRef", "GraphModelRegistry"]

DEFAULT_GRAPH_MODEL_DIR = "ml/artifacts/graph"
_SPECS = {"graphsage": GRAPHSAGE_SPEC, "graph_autoencoder": GRAPHSAGE_SPEC, "gat": GAT_SPEC}


@dataclass(frozen=True)
class GraphModelRef:
    name: str
    version: str
    method: str
    task: str
    feature_schema_version: str
    path: Path


def _latest(model_root: Path) -> Path | None:
    versions = sorted((p for p in model_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    return versions[-1] if versions else None


class GraphModelRegistry:
    def __init__(self, model_dir: str | os.PathLike[str]) -> None:
        self._dir = Path(model_dir)

    @classmethod
    def from_env(cls) -> GraphModelRegistry:
        return cls(os.environ.get("SM_ML_GRAPH_MODEL_DIR", DEFAULT_GRAPH_MODEL_DIR))

    def available(self) -> list[GraphModelRef]:
        if not self._dir.is_dir():
            return []
        refs: list[GraphModelRef] = []
        for model_root in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            vdir = _latest(model_root)
            if vdir is None or not (vdir / "metadata.json").exists():
                continue
            meta = json.loads((vdir / "metadata.json").read_text(encoding="utf-8"))
            refs.append(GraphModelRef(
                name=model_root.name,
                version=str(meta.get("model_version", vdir.name)),
                method=str(meta.get("method", model_root.name)),
                task=str(meta.get("task", "node_anomaly")),
                feature_schema_version=str(meta.get("feature_schema_version", "unknown")),
                path=vdir,
            ))
        return refs

    def load(self, name: str) -> GnnNodeAnomalyModel:
        ref = next((r for r in self.available() if r.name == name), None)
        if ref is None:
            raise GraphModelUnavailable(f"no registered graph model named {name!r} under {self._dir}")
        spec = _SPECS.get(ref.method)
        if spec is None:
            raise GraphModelUnavailable(f"registry cannot serve graph method {ref.method!r}")
        return GnnNodeAnomalyModel(
            spec=spec, model_version=ref.version, checkpoint=ref.path / "model.pt", method=ref.method,
        )
