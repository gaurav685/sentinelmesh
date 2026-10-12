"""Phase 1's modern-flow-dataset benchmark (CICIDS2017, UNSW-NB15).

A second, separate evaluation path alongside `harness.run_benchmark`
(NSL-KDD) -- not a replacement. It operates on `sm_ml.datasets.common.FlowDataset`
rather than `nsl_kdd.BenchmarkDataset`; the two are structurally compatible
(same `rows`/`labels`/`feature_names`/`sha256` shape), so the unsupervised
fitters (`isolation_forest`, `autoencoder`) are reused directly from
`harness` rather than reimplemented. `gradient_boosting` is supervised and
fit on the full labelled train split, not the benign-only subset the other
two use -- that split is handled here, not in `harness.run_benchmark`,
because unlike that function this one needs to know each model's real
label requirement rather than applying one fitting convention to all of
them.

Extra metrics the NSL-KDD path has no need for: PR-AUC, recall@1%FPR,
per-attack-class recall (from `FlowDataset.attack_types`, never just the
binary label), and a 95% bootstrap CI on ROC-AUC. All real, computed by
`sm_ml_training.benchmark.metrics` (stdlib-only, same auditability
discipline as `roc_auc`), never estimated.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from sm_ml.datasets.common import FlowDataset

from .harness import ModelName, _environment, _fit_autoencoder, _fit_gradient_boosting, _fit_isolation_forest
from .metrics import bootstrap_ci, per_class_recall, pr_auc, precision_recall_f1_fpr, recall_at_fpr, roc_auc

__all__ = ["FlowBenchmarkRun", "run_flow_benchmark"]

_SUPERVISED_MODELS: frozenset[ModelName] = frozenset({"gradient_boosting"})
_TARGET_FPR = 0.01
# A test split at Phase 1's real scale (hundreds of thousands of rows) makes
# the NSL-KDD harness's one-row-at-a-time Python loop (`harness._score_*`,
# fine at NSL-KDD's 22,544 rows) and a full-population bootstrap both
# impractical -- found by actually timing both against the real downloaded
# data, not assumed. Scoring below calls each fitted model once on the
# whole matrix (real vectorised inference, same fitted object, not a
# different model); the bootstrap resamples from a fixed random subsample
# instead of the full test split when it's larger than this.
_BOOTSTRAP_MAX_N = 20_000
_AUTOENCODER_SCORE_CHUNK = 50_000


def _real_benign_label(test: FlowDataset) -> str:
    """`FlowDataset.attack_types`'s real benign string varies by dataset --
    `"BENIGN"` for CICIDS2017, `"Normal"` for UNSW-NB15 (both are each
    loader's own real convention, not something to hardcode one of here).
    Derived from the real binary label (the most common attack-type string
    among label==0 rows) so `per_class_recall` excludes the actual benign
    rows for either dataset, rather than only ever matching `"BENIGN"` and
    silently leaving UNSW-NB15's `"Normal"` rows in the per-attack-class
    breakdown mislabelled as an attack category."""
    counts = Counter(t for t, y in zip(test.attack_types, test.labels, strict=True) if y == 0)
    return counts.most_common(1)[0][0] if counts else "BENIGN"


def _batch_score_isolation_forest(forest: Any, rows: list[list[float]]) -> tuple[list[float], list[int]]:
    import numpy as np

    x = np.asarray(rows, dtype=float)
    scores = (-forest.decision_function(x)).tolist()
    preds = [1 if p == -1 else 0 for p in forest.predict(x)]
    return scores, preds


def _batch_score_autoencoder(fitted: Any, rows: list[list[float]]) -> tuple[list[float], list[int]]:
    import torch

    module, threshold = fitted
    scores: list[float] = []
    with torch.no_grad():
        for start in range(0, len(rows), _AUTOENCODER_SCORE_CHUNK):
            chunk = torch.tensor(rows[start : start + _AUTOENCODER_SCORE_CHUNK], dtype=torch.float32)
            errs = torch.mean((module(chunk) - chunk) ** 2, dim=1)
            scores.extend(errs.tolist())
    preds = [1 if s >= threshold else 0 for s in scores]
    return scores, preds


def _batch_score_gradient_boosting(model: Any, rows: list[list[float]]) -> tuple[list[float], list[int]]:
    import numpy as np

    probs = model._booster.predict(np.asarray(rows, dtype=float)).tolist()
    preds = [1 if p >= model._threshold else 0 for p in probs]
    return probs, preds


class FlowBenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    train_sha256: str
    test_sha256: str
    n_train: int
    n_train_used_for_fit: int
    n_test: int
    n_test_anomalous: int
    model_name: str
    params: dict[str, Any]
    seed: int
    supervised: bool
    metrics: dict[str, float]
    per_class_recall: dict[str, float]
    roc_auc_ci95: tuple[float, float] | None
    roc_auc_ci_sample_n: int | None
    held_out_attack_type: str | None
    held_out_recall: float | None
    n_held_out: int | None
    environment: dict[str, str | None]
    generated_at: datetime
    executed: bool = True


def run_flow_benchmark(
    train: FlowDataset,
    test: FlowDataset,
    *,
    model: ModelName,
    seed: int = 1337,
    held_out_attack_type: str | None = None,
    held_out_rows: tuple[tuple[float, ...], ...] | None = None,
) -> FlowBenchmarkRun:
    """Fit `model` on `train`, score against `test`. If `held_out_attack_type`
    is given, `held_out_rows` must be the feature rows of that attack type
    (held out of `train` by the caller, e.g. via a day-based split or an
    explicit filter) -- `held_out_recall` is the real fraction of them this
    fit flags as anomalous, a genuine unseen-attack-category generalisation
    number, not estimated from the main test split."""
    supervised = model in _SUPERVISED_MODELS

    if supervised:
        fit_rows = [list(r) for r in train.rows]
        fit_labels = list(train.labels)
        if len(set(fit_labels)) < 2:
            raise ValueError(f"{model} needs both classes in the train split to fit")
    else:
        fit_rows = [list(r) for r, y in zip(train.rows, train.labels, strict=True) if y == 0]
        fit_labels = []
        if not fit_rows:
            raise ValueError("no benign rows in the train split to fit the baseline on")

    batch_score: Callable[[Any, list[list[float]]], tuple[list[float], list[int]]]
    if model == "isolation_forest":
        fitted, model_name, params = _fit_isolation_forest(fit_rows, train.feature_names, seed=seed)
        batch_score = _batch_score_isolation_forest
    elif model == "autoencoder":
        fitted, model_name, params = _fit_autoencoder(fit_rows, train.feature_names, seed=seed)
        batch_score = _batch_score_autoencoder
    elif model == "gradient_boosting":
        fitted, model_name, params = _fit_gradient_boosting(fit_rows, fit_labels, train.feature_names, seed=seed)
        batch_score = _batch_score_gradient_boosting
    else:
        raise ValueError(f"unsupported model for flow benchmark: {model!r}")

    start = time.perf_counter()
    scores, preds = batch_score(fitted, [list(r) for r in test.rows])
    elapsed_s = time.perf_counter() - start

    labels = list(test.labels)
    metrics: dict[str, float] = {}
    roc_ci: tuple[float, float] | None
    ci_n: int | None
    try:
        metrics["roc_auc"] = round(roc_auc(scores, labels), 6)
        metrics["pr_auc"] = round(pr_auc(scores, labels), 6)
        metrics[f"recall_at_{_TARGET_FPR}_fpr"] = recall_at_fpr(scores, labels, target_fpr=_TARGET_FPR)
        if len(scores) > _BOOTSTRAP_MAX_N:
            sub_idx = random.Random(seed).sample(range(len(scores)), _BOOTSTRAP_MAX_N)  # noqa: S311
            ci_scores = [scores[i] for i in sub_idx]
            ci_labels = [labels[i] for i in sub_idx]
            ci_n = _BOOTSTRAP_MAX_N
        else:
            ci_scores, ci_labels = scores, labels
            ci_n = len(scores)
        roc_ci = bootstrap_ci(roc_auc, ci_scores, ci_labels, n_resamples=500, seed=seed)
    except ValueError:
        metrics["roc_auc"] = float("nan")
        metrics["pr_auc"] = float("nan")
        metrics[f"recall_at_{_TARGET_FPR}_fpr"] = float("nan")
        roc_ci = None
        ci_n = None
    metrics.update(precision_recall_f1_fpr(preds, labels))
    metrics["mean_detection_latency_ms"] = round((elapsed_s / len(test.rows)) * 1000, 6)

    held_out_recall: float | None = None
    n_held_out: int | None = None
    if held_out_attack_type is not None and held_out_rows:
        _, held_preds = batch_score(fitted, [list(r) for r in held_out_rows])
        held_out_recall = round(sum(held_preds) / len(held_preds), 6)
        n_held_out = len(held_preds)

    return FlowBenchmarkRun(
        dataset_id=train.dataset_id.removesuffix("-train"),
        train_sha256=train.sha256,
        test_sha256=test.sha256,
        n_train=train.n_rows,
        n_train_used_for_fit=len(fit_rows),
        n_test=test.n_rows,
        n_test_anomalous=test.n_anomalous,
        model_name=model_name,
        params=params,
        seed=seed,
        supervised=supervised,
        metrics=metrics,
        per_class_recall=per_class_recall(preds, list(test.attack_types), benign_label=_real_benign_label(test)),
        roc_auc_ci95=roc_ci,
        roc_auc_ci_sample_n=ci_n,
        held_out_attack_type=held_out_attack_type,
        held_out_recall=held_out_recall,
        n_held_out=n_held_out,
        environment=_environment(),
        generated_at=datetime.now(UTC),
    )
