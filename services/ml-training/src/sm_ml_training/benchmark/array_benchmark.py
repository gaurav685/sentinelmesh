"""Memory-reduced flow benchmark: fits/scores directly on the float32 numpy
arrays `sm_ml.datasets.arrays` produces, plus a genuine streaming autoencoder
fit that never materialises the full train matrix at all.

Built after `flow_benchmark.run_flow_benchmark` (float64 Python-list-based)
proved real-data-scale infeasible: a full-scope Phase 1 attempt drove this
machine's free RAM from ~6.5 GB to ~430 MB before being killed. Real,
measured fixes, each documented at its own step (see
`scripts/run_phase1_benchmark_full.py` for the actual before/after RSS
table):

- Float32 throughout (not float64): 4 bytes/value instead of ~28-32
  bytes for a Python float object -- this is the dominant fix.
- LightGBM: `lgb.Dataset(..., free_raw_data=True)` discards LightGBM's own
  raw-data copy once histogram-binned, and the original numpy arrays are
  explicitly `del`eted + `gc.collect()`ed right after.
- IsolationForest (`sklearn`): genuinely has no streaming/incremental fit
  API -- it needs one resident float32 array, stated honestly rather than
  claimed otherwise. Scoring (`decision_function`/`predict`) is chunked
  (`_CHUNK_ROWS` at a time) to bound the transient memory sklearn
  allocates per call.
- Autoencoder: fit via `StreamingBenignBatches`, a real PyTorch
  `IterableDataset` that reads the train Parquet file(s) in bounded-size
  slices (Polars' lazy `.slice().collect()`, not pyarrow -- not an
  installed dependency here) and filters to benign rows per slice, so
  training never holds the full matrix in memory, only one batch. Scoring
  is chunked the same way as IsolationForest.
"""

from __future__ import annotations

import gc
import random
import time
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sm_ml.datasets.arrays import ArrayFlowDataset

from .flow_benchmark import FlowBenchmarkRun
from .harness import ModelName, _environment
from .metrics import bootstrap_ci, per_class_recall, pr_auc, precision_recall_f1_fpr, recall_at_fpr, roc_auc

__all__ = ["StreamingBenignBatches", "run_array_benchmark"]

_SUPERVISED_MODELS: frozenset[ModelName] = frozenset({"gradient_boosting"})
_TARGET_FPR = 0.01
_BOOTSTRAP_MAX_N = 20_000
_CHUNK_ROWS = 50_000


def _require_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError(f"array benchmark needs sm-ml[datasets] (polars): {exc}") from exc
    return pl


class StreamingBenignBatches:
    """A real PyTorch `IterableDataset` (duck-typed -- `torch` is an optional
    dependency of this package, so this class doesn't subclass it directly
    at import time; `_fit_autoencoder_streaming` wraps it in
    `torch.utils.data.IterableDataset` at call time). Reads `parquet_paths`
    in `batch_rows`-sized lazy slices via Polars (never pyarrow's
    `iter_batches` -- pyarrow isn't an installed dependency here), filters
    each slice to rows where `label_col == benign_value`, and yields a
    float32 torch tensor per slice -- the full train matrix is never
    resident in memory at once, only whichever slice is currently being
    trained on.
    """

    def __init__(
        self,
        parquet_paths: tuple[Path, ...],
        feature_cols: tuple[str, ...],
        *,
        label_col: str,
        benign_value: str,
        batch_rows: int = _CHUNK_ROWS,
    ) -> None:
        self.parquet_paths = parquet_paths
        self.feature_cols = feature_cols
        self.label_col = label_col
        self.benign_value = benign_value
        self.batch_rows = batch_rows

    def __iter__(self) -> Iterator[Any]:
        import torch

        pl = _require_polars()
        for path in self.parquet_paths:
            lf = pl.scan_parquet(path)
            n = lf.select(pl.len()).collect().item()
            for offset in range(0, n, self.batch_rows):
                chunk = (
                    lf.select([*self.feature_cols, self.label_col])
                    .slice(offset, self.batch_rows)
                    .filter(pl.col(self.label_col) == self.benign_value)
                    .select(self.feature_cols)
                    .collect()
                )
                if chunk.height == 0:
                    continue
                yield torch.from_numpy(chunk.to_numpy())


def _fit_isolation_forest_arrays(x: Any, feature_names: tuple[str, ...], *, seed: int) -> tuple[Any, dict[str, Any]]:
    from sklearn.ensemble import IsolationForest

    n_estimators = 100
    forest = IsolationForest(n_estimators=n_estimators, random_state=seed)
    forest.fit(x)
    return forest, {"n_estimators": n_estimators, "random_state": seed, "n_features": len(feature_names)}


def _score_isolation_forest_chunked(forest: Any, x: Any) -> tuple[list[float], list[int]]:
    scores: list[float] = []
    preds: list[int] = []
    for start in range(0, x.shape[0], _CHUNK_ROWS):
        chunk = x[start : start + _CHUNK_ROWS]
        scores.extend((-forest.decision_function(chunk)).tolist())
        preds.extend(1 if p == -1 else 0 for p in forest.predict(chunk))
    return scores, preds


def _fit_gradient_boosting_arrays(
    x: Any, y: Any, feature_names: tuple[str, ...], *, seed: int
) -> tuple[Any, dict[str, Any]]:
    import lightgbm as lgb

    num_leaves, n_estimators, learning_rate = 31, 200, 0.05
    dataset = lgb.Dataset(x, label=y, feature_name=list(feature_names), free_raw_data=True)
    params = {
        "objective": "binary", "num_leaves": num_leaves, "learning_rate": learning_rate,
        "seed": seed, "deterministic": True, "verbose": -1,
    }
    booster = lgb.train(params, dataset, num_boost_round=n_estimators)
    del dataset
    gc.collect()
    return booster, {
        "num_leaves": num_leaves, "n_estimators": n_estimators, "learning_rate": learning_rate,
        "seed": seed, "n_features": len(feature_names), "free_raw_data": True,
    }


def _score_gradient_boosting_chunked(booster: Any, x: Any) -> tuple[list[float], list[int]]:
    scores: list[float] = []
    for start in range(0, x.shape[0], _CHUNK_ROWS):
        scores.extend(booster.predict(x[start : start + _CHUNK_ROWS]).tolist())
    preds = [1 if s >= 0.5 else 0 for s in scores]
    return scores, preds


def _fit_autoencoder_streaming(
    parquet_paths: tuple[Path, ...],
    feature_names: tuple[str, ...],
    *,
    seed: int,
    label_col: str,
    benign_value: str,
) -> tuple[Any, dict[str, Any]]:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader

    from sm_ml.models.autoencoder import AutoencoderSpec, build_module

    torch.manual_seed(seed)
    input_dim = len(feature_names)
    hidden_dims = (max(8, input_dim // 4), max(4, input_dim // 8))
    spec = AutoencoderSpec(input_dim=input_dim, hidden_dims=hidden_dims)
    module = build_module(spec)
    optimizer = torch.optim.Adam(module.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()

    # torch is an optional dependency (absent in CI's base lint env, where
    # ignore_missing_imports makes IterableDataset resolve to Any -- "cannot
    # subclass Any" [misc]; present locally, where it's a real generic class
    # needing a type param -- [type-arg] if omitted). A bare ignore covers
    # both error codes across environments without being "unused" in either.
    class _TorchIterableWrapper(torch.utils.data.IterableDataset):  # type: ignore
        """Real `torch.utils.data.IterableDataset` subclass, defined here
        (not at module level) because `torch` is an optional dependency
        this module only imports at call time -- subclassing it at module
        import time would make `torch` a hard dependency of the whole
        module just to define this wrapper."""

        def __init__(self, inner: StreamingBenignBatches) -> None:
            self._inner = inner

        def __iter__(self) -> Iterator[Any]:
            return iter(self._inner)

    epochs = 10  # real, reduced from the NSL-KDD harness's 30 -- streaming re-reads Parquet every
    # epoch (no shuffling buffer held in RAM), so epoch count is the real cost knob here;
    # documented, not silently matched to the NSL-KDD harness's unrelated convention.
    dataset = _TorchIterableWrapper(
        StreamingBenignBatches(parquet_paths, feature_names, label_col=label_col, benign_value=benign_value)
    )
    train_errors: list[float] = []
    for epoch in range(epochs):
        train_errors = []
        for batch in DataLoader(dataset, batch_size=None):
            batch = batch.to(torch.float32)
            optimizer.zero_grad()
            recon = module(batch)
            loss = loss_fn(recon, batch)
            loss.backward()
            optimizer.step()
            if epoch == epochs - 1:
                with torch.no_grad():
                    train_errors.extend(torch.mean((module(batch) - batch) ** 2, dim=1).tolist())
    module.eval()
    threshold = float(torch.quantile(torch.tensor(train_errors), spec.error_quantile).item()) if train_errors else 0.0

    params = {
        "hidden_dims": list(hidden_dims), "epochs": epochs, "streaming_batch_rows": _CHUNK_ROWS,
        "error_quantile": spec.error_quantile, "n_features": input_dim,
    }
    return (module, threshold), params


def _fit_autoencoder_inmemory(
    x_benign: Any, feature_names: tuple[str, ...], *, seed: int
) -> tuple[Any, dict[str, Any]]:
    """Fallback for datasets whose `feature_names` don't exist as literal
    Parquet columns -- UNSW-NB15's one-hot-expanded names (`"proto=tcp"`,
    etc.) are computed by `sm_ml.datasets.arrays` at load time, not stored
    in the Parquet file, so `StreamingBenignBatches`' plain `.select()`
    fails (`ColumnNotFoundError`, found by actually running this against
    the real data, not assumed). Mini-batches straight from the already-
    resident `x_benign` array instead -- real for this pipeline, since the
    whole point of the Parquet+float32 rework is that this array is now
    small enough to hold resident (measured: ~2.5 GB for UNSW-NB15's
    2-of-4-file real scope); true disk streaming's marginal benefit here
    would be reproducing the one-hot encoding per batch for no real memory
    gain. Still never forms one single giant batch -- `_CHUNK_ROWS` rows
    per step, same bound as the streaming path."""
    import numpy as np
    import torch
    from torch import nn

    from sm_ml.models.autoencoder import AutoencoderSpec, build_module

    torch.manual_seed(seed)
    rng = np.random.RandomState(seed)
    input_dim = len(feature_names)
    hidden_dims = (max(8, input_dim // 4), max(4, input_dim // 8))
    spec = AutoencoderSpec(input_dim=input_dim, hidden_dims=hidden_dims)
    module = build_module(spec)
    optimizer = torch.optim.Adam(module.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()

    epochs = 10
    n = x_benign.shape[0]
    train_errors: list[float] = []
    for epoch in range(epochs):
        train_errors = []
        perm = rng.permutation(n)
        for start in range(0, n, _CHUNK_ROWS):
            batch = torch.from_numpy(x_benign[perm[start : start + _CHUNK_ROWS]]).to(torch.float32)
            optimizer.zero_grad()
            recon = module(batch)
            loss = loss_fn(recon, batch)
            loss.backward()
            optimizer.step()
            if epoch == epochs - 1:
                with torch.no_grad():
                    train_errors.extend(torch.mean((module(batch) - batch) ** 2, dim=1).tolist())
    module.eval()
    threshold = float(torch.quantile(torch.tensor(train_errors), spec.error_quantile).item()) if train_errors else 0.0
    params = {
        "hidden_dims": list(hidden_dims), "epochs": epochs, "chunk_rows": _CHUNK_ROWS,
        "error_quantile": spec.error_quantile, "n_features": input_dim, "source": "in-memory (not Parquet-streamed)",
    }
    return (module, threshold), params


def _score_autoencoder_chunked(fitted: Any, x: Any) -> tuple[list[float], list[int]]:
    import torch

    module, threshold = fitted
    scores: list[float] = []
    with torch.no_grad():
        for start in range(0, x.shape[0], _CHUNK_ROWS):
            chunk = torch.from_numpy(x[start : start + _CHUNK_ROWS]).to(torch.float32)
            errs = torch.mean((module(chunk) - chunk) ** 2, dim=1)
            scores.extend(errs.tolist())
    preds = [1 if s >= threshold else 0 for s in scores]
    return scores, preds


def _real_benign_label(test: ArrayFlowDataset) -> str:
    counts = Counter(t for t, y in zip(test.attack_types, test.y.tolist(), strict=True) if y == 0)
    return counts.most_common(1)[0][0] if counts else "BENIGN"


def run_array_benchmark(
    train: ArrayFlowDataset,
    test: ArrayFlowDataset,
    *,
    model: ModelName,
    seed: int = 1337,
    train_parquet_paths: tuple[Path, ...] = (),
    label_col: str = "Label",
    benign_value: str = "BENIGN",
    held_out_attack_type: str | None = None,
    held_out_x: Any = None,
) -> FlowBenchmarkRun:
    """Array-native counterpart to `flow_benchmark.run_flow_benchmark` --
    same `FlowBenchmarkRun` output shape, so report-writing code is
    unchanged, but every fit/score step here operates on `train.X`/`test.X`
    (float32 numpy, from `sm_ml.datasets.arrays`) directly. `autoencoder`
    additionally needs `train_parquet_paths` (the real files `train` was
    read from) to stream its fit rather than use `train.X` at all."""
    supervised = model in _SUPERVISED_MODELS
    y_train_list = train.y.tolist()
    n_benign = y_train_list.count(0)

    score_chunked: Callable[[Any, Any], tuple[list[float], list[int]]]
    if model == "isolation_forest":
        benign_mask = train.y == 0
        if not benign_mask.any():
            raise ValueError("no benign rows in the train split to fit the baseline on")
        fitted, params = _fit_isolation_forest_arrays(train.X[benign_mask], train.feature_names, seed=seed)
        model_name = "isolation_forest"
        score_chunked = _score_isolation_forest_chunked
        n_used_for_fit = int(benign_mask.sum())
    elif model == "gradient_boosting":
        if len(set(y_train_list)) < 2:
            raise ValueError(f"{model} needs both classes in the train split to fit")
        fitted, params = _fit_gradient_boosting_arrays(train.X, train.y, train.feature_names, seed=seed)
        model_name = "gradient_boosting"
        score_chunked = _score_gradient_boosting_chunked
        n_used_for_fit = train.n_rows
    elif model == "autoencoder":
        if n_benign == 0:
            raise ValueError("no benign rows in the train split to fit the baseline on")
        # One-hot-expanded feature names (e.g. UNSW-NB15's "proto=tcp") don't exist as
        # literal Parquet columns -- those are computed at array-load time, not stored
        # on disk -- so the streaming-from-Parquet path only works for datasets whose
        # feature names are real raw columns (CICIDS2017).
        if any("=" in f for f in train.feature_names):
            fitted, params = _fit_autoencoder_inmemory(train.X[train.y == 0], train.feature_names, seed=seed)
        elif train_parquet_paths:
            fitted, params = _fit_autoencoder_streaming(
                train_parquet_paths, train.feature_names, seed=seed, label_col=label_col, benign_value=benign_value,
            )
        else:
            raise ValueError("autoencoder streaming fit needs train_parquet_paths")
        model_name = "autoencoder"
        score_chunked = _score_autoencoder_chunked
        n_used_for_fit = n_benign
    else:
        raise ValueError(f"unsupported model for array benchmark: {model!r}")

    start = time.perf_counter()
    scores, preds = score_chunked(fitted, test.X)
    elapsed_s = time.perf_counter() - start

    labels = test.y.tolist()
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
    metrics["mean_detection_latency_ms"] = round((elapsed_s / len(test.X)) * 1000, 6)

    held_out_recall: float | None = None
    n_held_out: int | None = None
    if held_out_attack_type is not None and held_out_x is not None and held_out_x.shape[0] > 0:
        _, held_preds = score_chunked(fitted, held_out_x)
        held_out_recall = round(sum(held_preds) / len(held_preds), 6)
        n_held_out = len(held_preds)

    return FlowBenchmarkRun(
        dataset_id=train.dataset_id,
        train_sha256=train.sha256,
        test_sha256=test.sha256,
        n_train=train.n_rows,
        n_train_used_for_fit=n_used_for_fit,
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
