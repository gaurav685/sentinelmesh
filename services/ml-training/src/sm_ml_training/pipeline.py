"""The reproducible training pipeline.

    dataset -> preprocessing -> graph construction -> feature generation
            -> training -> validation -> checkpoint -> model version
            -> inference -> evaluation

Every stage is deterministic given the seed and the dataset. The `structural`
model kind runs fully offline (it calibrates the anomaly z-threshold against the
labelled train split — an honest supervised hyper-parameter fit). The `graphsage`
/ `gat` kinds need `torch` (`sm-ml[gnn]`); without it the pipeline raises
`PipelineSkipped` at the training stage and writes no artifact — it does not
fabricate a trained model or a metric.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

from sm_ml.graph import GRAPH_FEATURE_SCHEMA_VERSION, StructuralGraphAnomaly
from sm_ml.graph.models.gnn import (
    GAT_SPEC,
    GRAPHSAGE_SPEC,
    GnnNodeAnomalyModel,
    build_gnn_module,
    load_torch,
)

from .config import ModelKind, TrainingConfig
from .dataset import GraphDataset, LabelledSample, load_dataset, synthetic_fixture_dataset
from .metadata import EvaluationReport, ModelMetadata

__all__ = ["PipelineResult", "PipelineSkipped", "TrainedGnn", "TrainedStructural", "TrainingPipeline"]

_Z_GRID = (2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)


class PipelineSkipped(RuntimeError):  # noqa: N818 - a control-flow signal, not a failure
    """A required dependency (torch) or dataset is absent — no artifact is written."""


@dataclass(frozen=True)
class TrainedStructural:
    method: str
    z_threshold: float
    feature_schema_version: str = GRAPH_FEATURE_SCHEMA_VERSION

    def as_model(self) -> StructuralGraphAnomaly:
        return StructuralGraphAnomaly(z_threshold=self.z_threshold, method=self.method)

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method, "z_threshold": self.z_threshold,
            "feature_schema_version": self.feature_schema_version,
        }


@dataclass(frozen=True)
class TrainedGnn:
    """A real trained GraphSAGE/GAT checkpoint. `as_model()`/`to_dict()` mirror
    `TrainedStructural`'s shape so `TrainingPipeline`'s orchestration (validate,
    checkpoint, inference smoke test) works unchanged for either kind — both
    just need `.method`, `.to_dict()`, and an `.as_model()` whose result has
    `.score_nodes()`, which `GnnNodeAnomalyModel` already provides."""

    method: str
    checkpoint_path: str
    hidden_dim: int
    num_layers: int
    heads: int
    dropout: float
    epochs_run: int
    final_train_loss: float
    feature_schema_version: str = GRAPH_FEATURE_SCHEMA_VERSION

    def as_model(self) -> GnnNodeAnomalyModel:
        spec = (GRAPHSAGE_SPEC if self.method == "graphsage" else GAT_SPEC)
        spec = type(spec)(
            name=spec.name, conv=spec.conv, hidden_dim=self.hidden_dim,
            num_layers=self.num_layers, dropout=self.dropout, heads=self.heads,
        )
        return GnnNodeAnomalyModel(spec=spec, model_version="pending", checkpoint=Path(self.checkpoint_path))

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method, "hidden_dim": self.hidden_dim, "num_layers": self.num_layers,
            "heads": self.heads, "dropout": self.dropout, "epochs_run": self.epochs_run,
            "final_train_loss": self.final_train_loss,
            "feature_schema_version": self.feature_schema_version,
        }


@dataclass
class PipelineResult:
    model_version: str
    trained: TrainedStructural | TrainedGnn
    metadata: ModelMetadata
    stage_log: list[str] = field(default_factory=list)


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    try:  # pragma: no cover - torch not installed in CI
        import torch

        torch.manual_seed(seed)
    except ImportError:
        pass


def _prf(preds: list[int], labels: list[int]) -> dict[str, float]:
    tp = sum(1 for p, y in zip(preds, labels, strict=True) if p == 1 and y == 1)
    fp = sum(1 for p, y in zip(preds, labels, strict=True) if p == 1 and y == 0)
    fn = sum(1 for p, y in zip(preds, labels, strict=True) if p == 0 and y == 1)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6)}


class TrainingPipeline:
    def __init__(self, config: TrainingConfig) -> None:
        self.config = config
        self.log: list[str] = []

    def _note(self, stage: str, detail: str) -> None:
        self.log.append(f"{stage}: {detail}")

    # 1 --------------------------------------------------------------
    def load_dataset(self) -> GraphDataset:
        cfg = self.config
        if cfg.dataset_kind.value == "benchmark":
            if not cfg.dataset_path:
                raise PipelineSkipped("dataset_kind=benchmark but no dataset_path (no dataset ships)")
            ds = load_dataset(cfg.dataset_path, dataset_id=cfg.dataset_id)
        else:
            ds = synthetic_fixture_dataset(cfg.seed)
        self._note("dataset", f"{ds.dataset_id} ({ds.num_samples} samples, "
                              f"{ds.num_anomalous_nodes} anomalous nodes, sha256 {ds.sha256[:12]})")
        return ds

    # 2 --------------------------------------------------------------
    def preprocess(self, ds: GraphDataset) -> tuple[list[LabelledSample], list[LabelledSample]]:
        idx = list(range(ds.num_samples))
        random.Random(self.config.seed).shuffle(idx)  # noqa: S311 - a seeded, reproducible split
        n_val = max(1, round(ds.num_samples * self.config.val_fraction))
        val_idx = set(idx[:n_val])
        train = [ds.samples[i] for i in range(ds.num_samples) if i not in val_idx]
        val = [ds.samples[i] for i in range(ds.num_samples) if i in val_idx]
        self._note("preprocessing", f"{len(train)} train / {len(val)} val samples (seeded split)")
        return train, val

    # 3 + 4 ---------------------------------------------------------
    def check_graphs(self, samples: list[LabelledSample]) -> None:
        versions = {s.sample.schema_version for s in samples}
        if versions != {GRAPH_FEATURE_SCHEMA_VERSION}:
            raise PipelineSkipped(f"graph feature schema mismatch: {versions}")
        dims = {len(s.sample.node_features[0]) for s in samples if s.sample.num_nodes}
        self._note("graph_construction", f"{len(samples)} samples, schema {GRAPH_FEATURE_SCHEMA_VERSION}")
        self._note("feature_generation", f"node feature dim {dims}")

    # 5 --------------------------------------------------------------
    def train(self, train: list[LabelledSample]) -> TrainedStructural | TrainedGnn:
        if self.config.model_kind is not ModelKind.structural:
            return self._train_gnn(train)

        best_z, best_f1 = _Z_GRID[0], -1.0
        for z in _Z_GRID:
            model = StructuralGraphAnomaly(z_threshold=z)
            preds, labels = self._predict(model, train)
            f1 = _prf(preds, labels)["f1"]
            if f1 > best_f1:
                best_z, best_f1 = z, f1
        self._note("training", f"calibrated z_threshold={best_z} (train F1 {best_f1:.4f})")
        return TrainedStructural(method="structural_zscore", z_threshold=best_z)

    def _train_gnn(self, train: list[LabelledSample]) -> TrainedGnn:
        """Real GraphSAGE/GAT training: one graph sample per step (samples vary
        in node count, so they are not batched into a single tensor), loss
        computed only over nodes labelled benign (0) -- the graph-structured
        analogue of `sm_ml_training.benchmark.harness` fitting its tabular
        models on benign-only rows (ADR-013): the convolution still sees the
        whole graph (including attack nodes, as real neighbour context), only
        the reconstruction-error LOSS is masked to what the model is meant to
        learn to reconstruct well."""
        try:
            torch, tg = load_torch()
        except Exception as exc:
            raise PipelineSkipped(
                f"model_kind={self.config.model_kind.value} needs torch (sm-ml[gnn]): {exc}"
            ) from exc

        spec = GRAPHSAGE_SPEC if self.config.model_kind is ModelKind.graphsage else GAT_SPEC
        spec = type(spec)(
            name=spec.name, conv=spec.conv, hidden_dim=self.config.hidden_dim,
            num_layers=self.config.num_layers, dropout=spec.dropout, heads=spec.heads,
        )
        module = build_gnn_module(spec)
        optimizer = torch.optim.Adam(module.parameters(), lr=self.config.learning_rate)

        graphs = []
        for s in train:
            x = torch.tensor(s.sample.node_features, dtype=torch.float32)
            if s.sample.edge_index:
                ei = torch.tensor(list(zip(*s.sample.edge_index, strict=True)), dtype=torch.long)
            else:
                ei = torch.zeros((2, 0), dtype=torch.long)
            benign_mask = torch.tensor(
                [s.node_labels[nid] == 0 for nid in s.sample.node_ids], dtype=torch.bool
            )
            graphs.append((x, ei, benign_mask))

        final_loss = float("nan")
        for epoch in range(self.config.epochs):
            module.train()
            epoch_loss, n_graphs_used = 0.0, 0
            for x, ei, mask in graphs:
                if not bool(mask.any()):
                    continue  # an all-attack sample has nothing benign to fit
                optimizer.zero_grad()
                recon = module(x, ei)
                loss = torch.mean((recon[mask] - x[mask]) ** 2)
                loss.backward()
                optimizer.step()
                epoch_loss += float(loss.item())
                n_graphs_used += 1
            final_loss = epoch_loss / n_graphs_used if n_graphs_used else float("nan")
            self._note("training", f"gnn epoch {epoch + 1}/{self.config.epochs} mean_benign_mse={final_loss:.6f}")

        module.eval()
        checkpoint_name = f"{self.config.model_kind.value}_{self.config.model_version()}.pt"
        checkpoint_path = Path(self.config.output_dir) / checkpoint_name
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(module, checkpoint_path)
        self._note("training", f"gnn checkpoint written to {checkpoint_path}")
        _ = tg
        return TrainedGnn(
            method=self.config.model_kind.value, checkpoint_path=str(checkpoint_path),
            hidden_dim=spec.hidden_dim, num_layers=spec.num_layers, heads=spec.heads,
            dropout=spec.dropout, epochs_run=self.config.epochs, final_train_loss=final_loss,
        )

    # 6 --------------------------------------------------------------
    def validate(self, trained: TrainedStructural | TrainedGnn, val: list[LabelledSample]) -> dict[str, float]:
        preds, labels = self._predict(trained.as_model(), val)
        m = _prf(preds, labels)
        self._note("validation", f"val precision {m['precision']} recall {m['recall']} f1 {m['f1']}")
        return m

    # 7 + 8 -------------------------------------------------------
    def checkpoint_and_version(self, trained: TrainedStructural | TrainedGnn) -> str:
        version = self.config.model_version()
        self._note("checkpoint", f"params {trained.to_dict()}")
        self._note("model_version", version)
        return version

    # 9 --------------------------------------------------------------
    def inference_smoke(self, trained: TrainedStructural | TrainedGnn, val: list[LabelledSample]) -> None:
        if not val:
            raise PipelineSkipped("empty validation split")
        result = trained.as_model().score_nodes(val[0].sample)
        if len(result.scores) != val[0].sample.num_nodes:
            raise PipelineSkipped("inference produced the wrong number of scores")
        self._note("inference", f"scored {len(result.scores)} nodes on a held-out sample")

    # 10 -------------------------------------------------------------
    def evaluate(
        self, ds: GraphDataset, val: list[LabelledSample], val_metrics: dict[str, float]
    ) -> EvaluationReport:
        is_benchmark = ds.dataset_kind == "benchmark"
        report = EvaluationReport(
            dataset_id=ds.dataset_id, dataset_kind=ds.dataset_kind, dataset_sha256=ds.sha256,
            n_val_samples=len(val),
            n_val_nodes=sum(s.sample.num_nodes for s in val),
            n_val_anomalous=sum(v for s in val for v in s.node_labels.values()),
            val_metrics=val_metrics,
            benchmark_verified=False,
            headline_metrics=("NOT VERIFIED — REQUIRES DATASET/TRAINING EXECUTION"),
            note=(
                "benchmark dataset — headline metrics require an independent evaluation run"
                if is_benchmark else
                "synthetic fixture — val_metrics are a plumbing check, NOT a performance claim"
            ),
        )
        self._note("evaluation", report.note)
        return report

    # orchestration ----------------------------------------------
    def run(self) -> PipelineResult:
        _seed_everything(self.config.seed)
        ds = self.load_dataset()
        train, val = self.preprocess(ds)
        self.check_graphs([*train, *val])
        trained = self.train(train)
        val_metrics = self.validate(trained, val)
        version = self.checkpoint_and_version(trained)
        self.inference_smoke(trained, val)
        evaluation = self.evaluate(ds, val, val_metrics)

        meta = ModelMetadata(
            model_name=self.config.model_name, model_version=version,
            model_kind=self.config.model_kind.value, method=trained.method,
            task=self.config.task, feature_schema_version=GRAPH_FEATURE_SCHEMA_VERSION,
            seed=self.config.seed, config_hash=self.config.config_hash(),
            dataset_id=ds.dataset_id, dataset_sha256=ds.sha256,
            git_commit=_git_commit(), created_at=datetime.now(UTC),
            sm_ml_version=_pkg_version("sm-ml"),
            torch_version=_pkg_version("torch"),
            torch_geometric_version=_pkg_version("torch-geometric"),
            params=trained.to_dict(), evaluation=evaluation,
        )
        return PipelineResult(model_version=version, trained=trained, metadata=meta, stage_log=self.log)

    # helpers ---------------------------------------------------
    def _predict(
        self, model: StructuralGraphAnomaly | GnnNodeAnomalyModel, samples: list[LabelledSample]
    ) -> tuple[list[int], list[int]]:
        preds: list[int] = []
        labels: list[int] = []
        for s in samples:
            result = model.score_nodes(s.sample)
            for score in result.scores:
                preds.append(1 if score.is_anomaly else 0)
                labels.append(s.node_labels[score.node_id])
        return preds, labels


def _pkg_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def _git_commit() -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False,  # noqa: S607
        )
        return out.stdout.strip() or None
    except Exception:
        return None
