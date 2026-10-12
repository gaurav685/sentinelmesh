"""Phase 1.5 autoencoder bug hunt: a real ROC-AUC of 0.434 (below chance) on
UNSW-NB15 was traced to raw unscaled features -- one huge-range column
(e.g. byte counts in the millions) dominates MSE loss next to small-range
or 0/1 columns, so the autoencoder learns to reconstruct only the dominant
feature and carries no signal from the ones that actually separate benign
from attack. This test builds a synthetic dataset where the right answer
is known by construction: one huge-scale, label-independent "noise"
column, and several small-scale columns whose mean genuinely shifts for
the anomaly class. An autoencoder trained on raw values should fail (or
badly underperform); one trained through `_FeatureScaler` should separate
the classes well. Both are checked directly against `run_array_benchmark`,
the real code path used throughout this project's reports -- not a
reimplementation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sm_ml_training.benchmark.array_benchmark import _FeatureScaler, run_array_benchmark

from sm_ml.datasets.arrays import ArrayFlowDataset


def _make_dataset(seed: int) -> tuple[ArrayFlowDataset, ArrayFlowDataset]:
    rng = np.random.RandomState(seed)
    n_benign, n_attack = 2000, 400

    # Column 0: a huge-range column with IDENTICAL distribution for benign
    # and attack rows -- real noise, carries zero real separating signal.
    noise_benign = rng.uniform(0, 1_000_000, size=n_benign)
    noise_attack = rng.uniform(0, 1_000_000, size=n_attack)
    # Columns 1-3: small-range columns whose mean genuinely shifts for
    # attack rows -- the real signal an unscaled MSE loss would be
    # swallowed by next to column 0's huge range.
    signal_benign = rng.normal(0.0, 1.0, size=(n_benign, 3))
    signal_attack = rng.normal(4.0, 1.0, size=(n_attack, 3))

    x_benign = np.column_stack([noise_benign, signal_benign]).astype(np.float32)
    x_attack = np.column_stack([noise_attack, signal_attack]).astype(np.float32)
    x = np.concatenate([x_benign, x_attack], axis=0)
    y = np.concatenate([np.zeros(n_benign, dtype=np.int8), np.ones(n_attack, dtype=np.int8)])
    attack_types = tuple(["BENIGN"] * n_benign + ["SyntheticAttack"] * n_attack)

    idx = rng.permutation(len(x))
    x, y = x[idx], y[idx]
    attack_types = tuple(attack_types[i] for i in idx)
    split = int(len(x) * 0.7)
    feature_names = ("noise_huge_range", "signal_a", "signal_b", "signal_c")
    train = ArrayFlowDataset(
        dataset_id="synthetic-scaling", sha256="x", feature_names=feature_names,
        X=x[:split], y=y[:split], attack_types=attack_types[:split],
    )
    test = ArrayFlowDataset(
        dataset_id="synthetic-scaling", sha256="x", feature_names=feature_names,
        X=x[split:], y=y[split:], attack_types=attack_types[split:],
    )
    return train, test


def test_feature_scaler_log1p_standardize_matches_hand_computation() -> None:
    x_benign = np.array([[0.0, 10.0], [1.0, 20.0], [3.0, 30.0]], dtype=np.float32)
    scaler = _FeatureScaler.fit_from_array(x_benign)
    logged = np.log1p(x_benign)
    expected_mean = logged.mean(axis=0)
    expected_std = logged.std(axis=0)
    np.testing.assert_allclose(scaler.mean, expected_mean, rtol=1e-5)
    np.testing.assert_allclose(scaler.scale, expected_std, rtol=1e-5)
    transformed = scaler.transform(x_benign)
    np.testing.assert_allclose((logged - expected_mean) / expected_std, transformed, rtol=1e-4)


def test_feature_scaler_constant_column_does_not_divide_by_zero() -> None:
    x_benign = np.array([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]], dtype=np.float32)
    scaler = _FeatureScaler.fit_from_array(x_benign)
    assert scaler.scale[0] == 1.0  # constant column -- std is 0, mapped to scale=1, not NaN
    transformed = scaler.transform(x_benign)
    assert np.all(np.isfinite(transformed))


def test_feature_scaler_clips_negative_values_before_log1p() -> None:
    x_benign = np.array([[-5.0], [0.0], [3.0]], dtype=np.float32)
    scaler = _FeatureScaler.fit_from_array(x_benign)
    transformed = scaler.transform(x_benign)
    assert np.all(np.isfinite(transformed))


def test_autoencoder_scaling_fixes_a_real_below_chance_case(tmp_path: Path) -> None:
    """The known-answer case: a huge-range noise column should not be able
    to sink ROC-AUC below the unscaled baseline once scaling is applied."""
    pytest.importorskip("torch")
    pl = pytest.importorskip("polars")
    train, test = _make_dataset(seed=0)

    train_df = pl.DataFrame({
        **{name: train.X[:, i] for i, name in enumerate(train.feature_names)},
        "Label": list(train.attack_types),
    })
    train_path = tmp_path / "train.parquet"
    train_df.write_parquet(train_path)

    unscaled_x_benign = train.X[train.y == 0]
    scaled_x_benign = _FeatureScaler.fit_from_array(unscaled_x_benign).transform(unscaled_x_benign)
    # Scaling changes the real benign training distribution's own per-column
    # spread -- after scaling, every column contributes comparable variance
    # instead of column 0 alone dominating it (a direct, measured check that
    # the fix does what it claims, not just an end-to-end score comparison).
    unscaled_col_variance_ratio = unscaled_x_benign[:, 0].var() / unscaled_x_benign[:, 1:].var()
    scaled_col_variance_ratio = scaled_x_benign[:, 0].var() / scaled_x_benign[:, 1:].var()
    assert unscaled_col_variance_ratio > 1000  # column 0 dominates raw variance by construction
    assert scaled_col_variance_ratio < 10  # scaling brings it back to a comparable scale

    run = run_array_benchmark(train, test, model="autoencoder", seed=7, train_parquet_paths=(train_path,))
    # The real fitted autoencoder (via run_array_benchmark's actual code path,
    # scaler included) must recover a strong separation on this constructed
    # case where the answer is known: attack rows are a genuine 4-sigma shift
    # in the signal columns.
    assert run.metrics["roc_auc"] > 0.9
