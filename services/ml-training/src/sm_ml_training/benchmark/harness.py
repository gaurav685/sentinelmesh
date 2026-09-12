"""The reproducible tabular-benchmark run (R24).

Two evaluated methods, both real and both scored the same way:

- `"statistical"` — `sm_ml.models.StatisticalModel`, the platform's own
  always-available detector (stdlib only, no new dependency).
- `"isolation_forest"` — scikit-learn's `IsolationForest`, trained directly
  in this harness (`sm-ml[serving]` — numpy + scikit-learn — is an optional
  dependency of `ml-training`; `run_benchmark` raises `ModelUnavailable` if
  it is absent rather than silently skipping or fabricating a result).
  This is a genuine second, independently-implemented method — the
  "baseline IDS comparison" R24 asks for — not a relabeling of the same
  detector.

Both are fit on the **benign-only** subset of the train split — they model
"normal" behavior, exactly as `detection-engine` fits the statistical
detector from a mostly-benign rolling window in production (ADR-013).
Fitting on the raw train split (NSL-KDD's train split is deliberately
near-balanced, ~48% attacks) would corrupt that baseline with attack
traffic and is not how either method is actually used — so it is not how
either is benchmarked. The fitted model is then scored against the held-out,
fully-labeled test split.

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
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from sm_ml.errors import ModelUnavailable
from sm_ml.models.statistical import DEFAULT_Z_THRESHOLD, StatisticalModel

from .metrics import precision_recall_f1_fpr, roc_auc
from .nsl_kdd import PREPROCESSING_VERSION, BenchmarkDataset

__all__ = ["BenchmarkRun", "run_benchmark"]

ModelName = Literal["statistical", "isolation_forest"]


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


def _fit_statistical(
    benign_rows: list[list[float]], feature_names: tuple[str, ...], *, z_threshold: float
) -> tuple[Any, str, dict[str, Any]]:
    model = StatisticalModel.fit(feature_names, benign_rows, z_threshold=z_threshold)
    params = {"z_threshold": z_threshold, "n_features": len(feature_names)}
    return model, model.method.value, params


def _score_statistical(model: Any, row: tuple[float, ...]) -> tuple[float, int]:
    result = model.score(row)
    return result.normalized_score, (1 if result.is_anomaly else 0)


def _fit_isolation_forest(
    benign_rows: list[list[float]], feature_names: tuple[str, ...], *, seed: int
) -> tuple[Any, str, dict[str, Any]]:
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError as exc:
        raise ModelUnavailable(
            f"isolation_forest needs sm-ml[serving] (numpy + scikit-learn): {exc}"
        ) from exc

    n_estimators = 100
    forest = IsolationForest(n_estimators=n_estimators, random_state=seed)
    forest.fit(np.asarray(benign_rows, dtype=float))
    params = {"n_estimators": n_estimators, "random_state": seed, "n_features": len(feature_names)}
    return forest, "isolation_forest", params


def _score_isolation_forest(forest: Any, row: tuple[float, ...]) -> tuple[float, int]:
    import numpy as np

    x = np.asarray([list(row)], dtype=float)
    # decision_function: lower = more abnormal. Negate so higher = more
    # anomalous, matching sm_ml.models' own score convention.
    raw = float(-forest.decision_function(x)[0])
    pred = 1 if forest.predict(x)[0] == -1 else 0
    return raw, pred


def run_benchmark(
    train: BenchmarkDataset,
    test: BenchmarkDataset,
    *,
    model: ModelName = "statistical",
    seed: int = 1337,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> BenchmarkRun:
    benign_rows = [list(r) for r, y in zip(train.rows, train.labels, strict=True) if y == 0]
    if not benign_rows:
        raise ValueError("no benign rows in the train split to fit the baseline on")

    score_one: Callable[[Any, tuple[float, ...]], tuple[float, int]]
    if model == "statistical":
        fitted, model_name, params = _fit_statistical(
            benign_rows, train.feature_names, z_threshold=z_threshold
        )
        score_one = _score_statistical
    elif model == "isolation_forest":
        fitted, model_name, params = _fit_isolation_forest(
            benign_rows, train.feature_names, seed=seed
        )
        score_one = _score_isolation_forest
    else:
        raise ValueError(f"unknown model: {model!r}")

    # Timed region: real per-row scoring latency only — fitting is a one-time
    # cost, not what "detection latency" means. Each call scores exactly one
    # row, matching sm_ml.models.AnomalyModel's real one-event-at-a-time
    # serving contract (never a batch the production path never takes).
    scores: list[float] = []
    preds: list[int] = []
    start = time.perf_counter()
    for row in test.rows:
        s, p = score_one(fitted, row)
        scores.append(s)
        preds.append(p)
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
        model_name=model_name,
        params=params,
        seed=seed,
        metrics=metrics,
        environment=_environment(),
        generated_at=datetime.now(UTC),
    )
