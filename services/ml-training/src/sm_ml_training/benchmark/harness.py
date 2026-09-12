"""The reproducible tabular-benchmark run (R24).

Evaluation design: the unsupervised baseline (`sm_ml.models.StatisticalModel`)
is fit on the **benign-only** subset of the train split — it models "normal"
behavior, exactly as `detection-engine` fits it from a mostly-benign rolling
window in production (ADR-013). Fitting it on the raw train split (NSL-KDD's
train split is deliberately near-balanced, ~48% attacks) would corrupt the
median/MAD baseline with attack traffic and is not how the model is actually
used — so it is not how it is benchmarked either. The fitted model is then
scored against the held-out, fully-labeled test split.

A `BenchmarkRun` records everything a second run needs to reproduce or
contest the number: which dataset (id + sha256 of the exact bytes read),
preprocessing version, the split sizes, the model + its parameters, the
metrics, and the real environment (package versions, git commit, timestamp).
`executed=True` is only ever set by an actual call to `run_benchmark` against
a real file — nothing else in this module can produce a `BenchmarkRun`.
"""

from __future__ import annotations

import platform
import time
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from typing import Any

from pydantic import BaseModel, ConfigDict

from sm_ml.models.statistical import DEFAULT_Z_THRESHOLD, StatisticalModel

from .metrics import precision_recall_f1_fpr, roc_auc
from .nsl_kdd import PREPROCESSING_VERSION, BenchmarkDataset

__all__ = ["BenchmarkRun", "run_benchmark"]


class BenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    train_sha256: str
    test_sha256: str
    preprocessing_version: str
    n_train: int
    n_train_benign_used_for_fit: int
    n_test: int
    n_test_anomalous: int
    model_name: str
    params: dict[str, Any]
    seed: int
    metrics: dict[str, float]
    environment: dict[str, str | None]
    generated_at: datetime
    executed: bool = True


def _environment() -> dict[str, str | None]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "sm_ml_version": _pkg_version("sm-ml"),
        "sm_ml_training_version": _pkg_version("sm-ml-training"),
        "git_commit": _git_commit(),
    }


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


def run_benchmark(
    train: BenchmarkDataset,
    test: BenchmarkDataset,
    *,
    seed: int = 1337,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> BenchmarkRun:
    benign_rows = [list(r) for r, y in zip(train.rows, train.labels, strict=True) if y == 0]
    if not benign_rows:
        raise ValueError("no benign rows in the train split to fit the baseline on")

    model = StatisticalModel.fit(train.feature_names, benign_rows, z_threshold=z_threshold)

    scores: list[float] = []
    preds: list[int] = []
    start = time.perf_counter()
    for row in test.rows:
        result = model.score(row)
        scores.append(result.normalized_score)
        preds.append(1 if result.is_anomaly else 0)
    elapsed_s = time.perf_counter() - start

    labels = list(test.labels)
    metrics: dict[str, float] = {}
    try:
        metrics["roc_auc"] = round(roc_auc(scores, labels), 6)
    except ValueError:
        metrics["roc_auc"] = float("nan")  # only one class in the test split — genuinely undefined
    metrics.update(precision_recall_f1_fpr(preds, labels))
    metrics["mean_detection_latency_ms"] = round((elapsed_s / len(test.rows)) * 1000, 6)

    return BenchmarkRun(
        dataset_id=train.dataset_id.removesuffix("-train"),
        train_sha256=train.sha256,
        test_sha256=test.sha256,
        preprocessing_version=PREPROCESSING_VERSION,
        n_train=train.n_rows,
        n_train_benign_used_for_fit=len(benign_rows),
        n_test=test.n_rows,
        n_test_anomalous=test.n_anomalous,
        model_name=model.method.value,
        params={"z_threshold": z_threshold, "n_features": len(train.feature_names)},
        seed=seed,
        metrics=metrics,
        environment=_environment(),
        generated_at=datetime.now(UTC),
    )
