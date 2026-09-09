"""GraphSAGE / GAT / graph-autoencoder — the trained-model boundary (Phase 8).

`torch` and `torch-geometric` are the optional `sm-ml[gnn]` dependency. `ml-training`
produces the weights; `ml-inference` serves them. This module is only the
**interface + architecture spec + loader**:

- import torch lazily; absent -> `GraphModelUnavailable` (a serving layer degrades
  to `sm_ml.graph.models.structural`, never fabricates a score).
- no checkpoint -> `GraphModelNotTrained`.
- a loaded model's `score_nodes` runs a real forward pass over the `GraphSample`
  converted to a `torch_geometric.data.Data`.

No accuracy / AUC number is defined or claimed here (ADR-024).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..construct import GraphSample
from ..schema import GRAPH_FEATURE_SCHEMA_VERSION
from .base import GraphModelNotTrained, GraphModelUnavailable, NodeAnomalyResult, NodeScore

__all__ = [
    "GAT_SPEC",
    "GRAPHSAGE_SPEC",
    "GNNArchitectureSpec",
    "GnnNodeAnomalyModel",
    "load_torch",
]

_ANOMALY_THRESHOLD = 0.8


def load_torch() -> tuple[Any, Any]:
    """Return `(torch, torch_geometric)` or raise `GraphModelUnavailable`."""
    try:
        import torch
        import torch_geometric
    except ImportError as exc:  # pragma: no cover - only where sm-ml[gnn] is absent
        raise GraphModelUnavailable(
            "torch / torch-geometric not installed (install sm-ml[gnn])"
        ) from exc
    return torch, torch_geometric


@dataclass(frozen=True)
class GNNArchitectureSpec:
    """A fixed, versioned architecture description. `ml-training` reads this so a
    checkpoint and the code that loads it cannot disagree."""

    name: str
    conv: str                       # "sage" | "gat"
    hidden_dim: int
    num_layers: int
    dropout: float
    heads: int                      # GAT only; 1 for SAGE
    feature_schema_version: str = GRAPH_FEATURE_SCHEMA_VERSION
    task: str = "node_anomaly"
    aggregation: str = "mean"
    activation: str = "relu"
    notes: str = ""


GRAPHSAGE_SPEC = GNNArchitectureSpec(
    name="graphsage", conv="sage", hidden_dim=64, num_layers=2, dropout=0.2, heads=1,
    notes="node-embedding + reconstruction head for unsupervised node anomaly",
)
GAT_SPEC = GNNArchitectureSpec(
    name="gat", conv="gat", hidden_dim=64, num_layers=2, dropout=0.2, heads=4,
    notes="attention-weighted node embeddings; reconstruction head",
)


@dataclass
class GnnNodeAnomalyModel:
    """A trained GraphSAGE- or GAT-based node-anomaly model. `method` distinguishes
    `graphsage` / `gat` / `graph_autoencoder` in the registry and the contract;
    the forward pass is the same reconstruction error."""

    spec: GNNArchitectureSpec
    model_version: str
    checkpoint: Path
    method: str = "graphsage"
    _module: Any = field(default=None, repr=False)

    def _forward_error(self, sample: GraphSample) -> list[float]:
        torch, tg = load_torch()
        if self._module is None:
            if not self.checkpoint.exists():
                raise GraphModelNotTrained(f"no checkpoint at {self.checkpoint}")
            self._module = torch.load(self.checkpoint, map_location="cpu", weights_only=False)
            self._module.eval()
        x = torch.tensor(sample.node_features, dtype=torch.float32)
        if sample.edge_index:
            ei = torch.tensor(list(zip(*sample.edge_index, strict=True)), dtype=torch.long)
        else:
            ei = torch.zeros((2, 0), dtype=torch.long)
        data = tg.data.Data(x=x, edge_index=ei)
        with torch.no_grad():
            recon = self._module(data.x, data.edge_index)
            err = torch.linalg.vector_norm(recon - data.x, dim=1)
        return [float(v) for v in err.tolist()]

    def score_nodes(self, sample: GraphSample) -> NodeAnomalyResult:
        vals = self._forward_error(sample)
        hi = max(vals) if vals else 1.0
        scores = tuple(
            NodeScore(
                node_id=nid, score=round(v, 6),
                normalized_score=round(v / hi if hi > 0 else 0.0, 6),
                is_anomaly=(v / hi if hi > 0 else 0.0) >= _ANOMALY_THRESHOLD,
            )
            for nid, v in zip(sample.node_ids, vals, strict=True)
        )
        return NodeAnomalyResult(
            method=self.method, model_version=self.model_version, threshold=_ANOMALY_THRESHOLD,
            scores=scores, feature_schema_version=GRAPH_FEATURE_SCHEMA_VERSION, confidence=0.0,
        )
