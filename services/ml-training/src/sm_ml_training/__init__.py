"""SentinelMesh ML training pipeline (Phase 8).

A reproducible offline pipeline:

    dataset -> preprocessing -> graph construction -> feature generation
            -> training -> validation -> checkpoint -> model version
            -> inference -> evaluation

Every stage is deterministic given the seed and the dataset. `structural` runs
fully offline (it calibrates the anomaly z-threshold against the labelled train
split). `graphsage` / `gat` need `torch` (`sm-ml[gnn]`); without it the pipeline
raises `PipelineSkipped` and writes nothing — it never fabricates a trained model
or a metric. No benchmark number is claimed without a registered dataset
(ADR-024 — no dataset ships).
"""

from __future__ import annotations

from .artifacts import write_artifact
from .config import DatasetKind, ModelKind, TrainingConfig
from .dataset import GraphDataset, LabelledSample, load_dataset, synthetic_fixture_dataset
from .metadata import EvaluationReport, ModelMetadata
from .pipeline import PipelineResult, PipelineSkipped, TrainedStructural, TrainingPipeline

__all__ = [
    "DatasetKind",
    "EvaluationReport",
    "GraphDataset",
    "LabelledSample",
    "ModelKind",
    "ModelMetadata",
    "PipelineResult",
    "PipelineSkipped",
    "TrainedStructural",
    "TrainingConfig",
    "TrainingPipeline",
    "load_dataset",
    "synthetic_fixture_dataset",
    "write_artifact",
]
