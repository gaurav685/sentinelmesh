"""Tabular IDS benchmark harness (R24; `ml/datasets/<name>/MANIFEST.md`).

Distinct from `sm_ml_training.pipeline` (the graph-model training pipeline,
Phase 8) — this evaluates the `sm_ml.models` anomaly-model family
(`AnomalyModel.score(features) -> AnomalyScore`) against a real, row-per-flow
tabular dataset. No dataset ships (ADR-024); a result exists only after a
real file staged under `SM_DATASET_ROOT` is actually read and scored.
"""

from __future__ import annotations

from .harness import BenchmarkRun, run_benchmark
from .metrics import confusion_counts, precision_recall_f1_fpr, roc_auc
from .persist import save_benchmark_run

__all__ = [
    "BenchmarkRun",
    "confusion_counts",
    "precision_recall_f1_fpr",
    "roc_auc",
    "run_benchmark",
    "save_benchmark_run",
]
