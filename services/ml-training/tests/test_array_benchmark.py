from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sm_ml_training.benchmark.array_benchmark import run_array_benchmark

from sm_ml.datasets.arrays import ArrayFlowDataset


def _synthetic(seed: int = 0) -> tuple[ArrayFlowDataset, ArrayFlowDataset]:
    rng = np.random.RandomState(seed)
    n = 400
    benign = rng.uniform(0, 1, size=(n, 3)).astype(np.float32)
    attack = rng.uniform(5, 8, size=(n // 5, 3)).astype(np.float32)
    x = np.concatenate([benign, attack], axis=0)
    y = np.concatenate([np.zeros(n, dtype=np.int8), np.ones(n // 5, dtype=np.int8)])
    attack_types = tuple(["BENIGN"] * n + ["DoS"] * (n // 5))
    idx = rng.permutation(len(x))
    x, y = x[idx], y[idx]
    attack_types = tuple(attack_types[i] for i in idx)
    split = int(len(x) * 0.75)
    train = ArrayFlowDataset(
        dataset_id="synthetic", sha256="x", feature_names=("a", "b", "c"),
        X=x[:split], y=y[:split], attack_types=attack_types[:split],
    )
    test = ArrayFlowDataset(
        dataset_id="synthetic", sha256="x", feature_names=("a", "b", "c"),
        X=x[split:], y=y[split:], attack_types=attack_types[split:],
    )
    return train, test


def test_run_array_benchmark_isolation_forest() -> None:
    train, test = _synthetic()
    run = run_array_benchmark(train, test, model="isolation_forest", seed=1)
    assert run.metrics["roc_auc"] > 0.8
    assert run.supervised is False


def test_run_array_benchmark_gradient_boosting_free_raw_data() -> None:
    pytest.importorskip("lightgbm")
    train, test = _synthetic()
    run = run_array_benchmark(train, test, model="gradient_boosting", seed=1)
    assert run.metrics["roc_auc"] > 0.9
    assert run.params["free_raw_data"] is True
    assert run.supervised is True


def test_run_array_benchmark_autoencoder_streams_from_parquet(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pl = pytest.importorskip("polars")

    train, test = _synthetic()
    df = pl.DataFrame({
        "a": train.X[:, 0], "b": train.X[:, 1], "c": train.X[:, 2],
        "Label": ["BENIGN" if v == 0 else "DoS" for v in train.y],
    })
    path = tmp_path / "train.parquet"
    df.write_parquet(path)
    run = run_array_benchmark(train, test, model="autoencoder", seed=1, train_parquet_paths=(path,))
    assert run.n_train_used_for_fit == int((train.y == 0).sum())
    assert "roc_auc" in run.metrics


def test_run_array_benchmark_autoencoder_without_parquet_paths_raises() -> None:
    train, test = _synthetic()
    with pytest.raises(ValueError, match="train_parquet_paths"):
        run_array_benchmark(train, test, model="autoencoder", seed=1)


def test_run_array_benchmark_autoencoder_onehot_features_use_inmemory_fallback() -> None:
    """One-hot-expanded feature names (e.g. UNSW-NB15's "proto=tcp") don't
    exist as literal Parquet columns -- `StreamingBenignBatches` would
    raise ColumnNotFoundError against the real file. No train_parquet_paths
    needed for this path; it must not try to stream at all."""
    pytest.importorskip("torch")
    train, test = _synthetic()
    train = ArrayFlowDataset(
        dataset_id=train.dataset_id, sha256=train.sha256,
        feature_names=("a", "b", "proto=tcp"), X=train.X, y=train.y, attack_types=train.attack_types,
    )
    run = run_array_benchmark(train, test, model="autoencoder", seed=1)
    assert run.params["source"] == "in-memory (not Parquet-streamed)"


def test_run_array_benchmark_no_benign_rows_raises() -> None:
    train, test = _synthetic()
    all_attack = ArrayFlowDataset(
        dataset_id="synthetic", sha256="x", feature_names=train.feature_names,
        X=train.X, y=np.ones_like(train.y), attack_types=train.attack_types,
    )
    with pytest.raises(ValueError, match="benign"):
        run_array_benchmark(all_attack, test, model="isolation_forest", seed=1)


def test_run_array_benchmark_held_out_attack_type() -> None:
    pytest.importorskip("lightgbm")
    train, test = _synthetic()
    held_out_rows = test.X[test.y == 1]
    run = run_array_benchmark(
        train, test, model="gradient_boosting", seed=1,
        held_out_attack_type="DoS", held_out_x=held_out_rows,
    )
    assert run.held_out_attack_type == "DoS"
    assert run.n_held_out == held_out_rows.shape[0]


def test_run_array_benchmark_calibration_targets_real_fpr_on_validation() -> None:
    pytest.importorskip("lightgbm")
    train, test = _synthetic()
    run = run_array_benchmark(train, test, model="gradient_boosting", seed=1, calibrate_at_fpr=0.1)
    assert "calibrated_threshold" in run.metrics
    assert run.metrics["calibration_target_fpr"] == pytest.approx(0.1)
    assert "precision_at_calibrated_threshold" in run.metrics
    assert "recall_at_calibrated_threshold" in run.metrics


def test_run_array_benchmark_no_calibration_keys_when_disabled() -> None:
    pytest.importorskip("lightgbm")
    train, test = _synthetic()
    run = run_array_benchmark(train, test, model="gradient_boosting", seed=1)
    assert "calibrated_threshold" not in run.metrics
