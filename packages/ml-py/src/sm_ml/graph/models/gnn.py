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
    "build_gnn_module",
    "gnn_module_class",
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


def gnn_module_class(conv: str) -> Any:
    """The trainable `nn.Module` class for `conv` ("sage" | "gat"): a 2-layer
    graph encoder down to `hidden_dim`, then one graph-conv layer back up to
    the input feature dimension -- a graph autoencoder whose reconstruction
    error at each node is the anomaly signal `_forward_error` already scores
    (same convention as `sm_ml.models.autoencoder`'s tabular reconstruction
    model). Defined at module scope, not inside this function's closure, so
    `torch.save`/`torch.load` of a whole trained module instance can pickle
    it -- a local class cannot be. Cached per `conv` kind after first build."""
    torch, tg = load_torch()
    # `nn: Any` deliberately, not `from torch import nn`: whether mypy sees
    # torch's real type stubs depends on whether `sm-ml[gnn]` is installed
    # in the *checking* environment (it is not in CI), which would otherwise
    # make the `type: ignore` below "needed" in one environment and "unused"
    # (itself a strict-mode error) in another.
    nn: Any = torch.nn

    attr = f"_GnnModule_{conv}"
    existing = globals().get(attr)
    if existing is not None:
        return existing

    if conv == "sage":
        conv_layer = tg.nn.SAGEConv
    elif conv == "gat":
        conv_layer = tg.nn.GATConv
    else:
        raise ValueError(f"unknown conv kind: {conv!r}")

    class _GnnModule(nn.Module):  # type: ignore[misc]
        def __init__(self, input_dim: int, hidden_dim: int, heads: int, dropout: float) -> None:
            super().__init__()
            kwargs = {"heads": heads} if conv == "gat" else {}
            out1 = hidden_dim * heads if conv == "gat" else hidden_dim
            self.conv1 = conv_layer(input_dim, hidden_dim, **kwargs)
            self.conv2 = conv_layer(out1, input_dim, **({"heads": 1} if conv == "gat" else {}))
            self.dropout = nn.Dropout(dropout)
            self.activation = nn.ReLU()

        def forward(self, x: Any, edge_index: Any) -> Any:
            h = self.activation(self.conv1(x, edge_index))
            h = self.dropout(h)
            return self.conv2(h, edge_index)

    _GnnModule.__qualname__ = attr
    _GnnModule.__name__ = attr
    globals()[attr] = _GnnModule
    _ = torch
    return _GnnModule


def build_gnn_module(spec: GNNArchitectureSpec) -> Any:
    """Build an untrained module per `spec` -- shared by `ml-training` (fits
    the weights) and this module's loader (reconstructs the architecture
    before unpickling a checkpoint's state)."""
    cls = gnn_module_class(spec.conv)
    return cls(
        input_dim=_graph_feature_dim(), hidden_dim=spec.hidden_dim,
        heads=spec.heads, dropout=spec.dropout,
    )


def _graph_feature_dim() -> int:
    from ..schema import GraphFeatureSchema

    return GraphFeatureSchema().node_feature_dim


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
            gnn_module_class(self.spec.conv)  # registers the class so the unpickler below can find it
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
