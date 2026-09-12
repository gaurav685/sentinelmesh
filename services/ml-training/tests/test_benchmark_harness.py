from __future__ import annotations

from pathlib import Path

import pytest
from sm_ml_training.benchmark.harness import run_benchmark
from sm_ml_training.benchmark.nsl_kdd import load_nsl_kdd

# Real NSL-KDD row shape (42 comma-separated columns, no header).
_TRAIN_ROWS = [
    "0,tcp,ftp_data,SF,491,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,2,0.00,0.00,0.00,0.00,1.00,0.00,0.00,150,25,0.17,0.03,0.17,0.00,0.00,0.00,0.05,0.00,normal,20",
    "0,udp,other,SF,146,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,13,1,0.00,0.00,0.00,0.00,0.08,0.15,0.00,255,1,0.00,0.60,0.88,0.00,0.00,0.00,0.00,0.00,normal,15",
    "0,tcp,private,S0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,123,6,1.00,1.00,0.00,0.00,0.05,0.07,0.00,255,26,0.10,0.05,0.00,0.00,1.00,1.00,0.00,0.00,neptune,19",
    "0,tcp,http,SF,300,200,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,5,5,0.00,0.00,0.00,0.00,1.00,0.00,0.00,10,10,0.00,0.00,0.00,0.00,0.00,0.00,0.00,0.00,normal,21",
]
_TEST_ROWS = [
    "0,tcp,http,SF,280,190,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,6,6,0.00,0.00,0.00,0.00,1.00,0.00,0.00,12,12,0.00,0.00,0.00,0.00,0.00,0.00,0.00,0.00,normal,21",
    "0,icmp,ecr_i,SF,1032,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,511,511,0.00,0.00,1.00,1.00,0.00,0.00,0.00,255,255,1.00,0.00,1.00,0.00,0.00,0.00,0.00,0.00,smurf,21",
]


@pytest.fixture
def dataset(tmp_path: Path):
    train_path = tmp_path / "KDDTrain+.txt"
    test_path = tmp_path / "KDDTest+.txt"
    train_path.write_text("\n".join(_TRAIN_ROWS) + "\n", encoding="utf-8")
    test_path.write_text("\n".join(_TEST_ROWS) + "\n", encoding="utf-8")
    return load_nsl_kdd(train_path, test_path)


def test_run_benchmark_is_reproducible_given_the_same_data_and_seed(dataset) -> None:
    train, test = dataset
    a = run_benchmark(train, test, seed=1337)
    b = run_benchmark(train, test, seed=1337)
    # every metric except real wall-clock timing must match exactly — the
    # model fit, scoring, and threshold are all deterministic given the data.
    timing_key = "mean_detection_latency_ms"
    a_metrics = {k: v for k, v in a.metrics.items() if k != timing_key}
    b_metrics = {k: v for k, v in b.metrics.items() if k != timing_key}
    assert a_metrics == b_metrics
    assert a.metrics[timing_key] > 0.0
    assert b.metrics[timing_key] > 0.0
    assert a.train_sha256 == b.train_sha256 == train.sha256
    assert a.test_sha256 == b.test_sha256 == test.sha256


def test_run_benchmark_fits_only_on_benign_train_rows(dataset) -> None:
    train, test = dataset
    run = run_benchmark(train, test, seed=1337)
    # 4 train rows, one ("neptune") is an attack -> 3 benign rows used for fit
    assert run.n_train == 4
    assert run.n_train_benign_used_for_fit == 3
    assert run.n_test == 2
    assert run.n_test_anomalous == 1


def test_run_benchmark_reports_real_metrics_never_a_placeholder(dataset) -> None:
    train, test = dataset
    run = run_benchmark(train, test, seed=1337)
    assert run.executed is True
    for key in ("precision", "recall", "f1", "false_positive_rate", "mean_detection_latency_ms"):
        assert key in run.metrics
        assert run.metrics[key] >= 0.0
    assert run.model_name == "mad_zscore"
    assert run.dataset_id == "nsl-kdd"
    assert run.preprocessing_version == "nsl-kdd-v1"
    assert run.environment["python_version"]


def test_isolation_forest_is_reproducible_given_the_same_seed(dataset) -> None:
    train, test = dataset
    try:
        import sklearn  # noqa: F401
    except ImportError:
        pytest.skip("sm-ml[serving] not installed")
    a = run_benchmark(train, test, model="isolation_forest", seed=7)
    b = run_benchmark(train, test, model="isolation_forest", seed=7)
    timing_key = "mean_detection_latency_ms"
    a_metrics = {k: v for k, v in a.metrics.items() if k != timing_key}
    b_metrics = {k: v for k, v in b.metrics.items() if k != timing_key}
    assert a_metrics == b_metrics
    assert a.model_name == "isolation_forest"
    assert a.params["random_state"] == 7


def test_isolation_forest_is_a_different_real_method_not_a_relabeling(dataset) -> None:
    train, test = dataset
    try:
        import sklearn  # noqa: F401
    except ImportError:
        pytest.skip("sm-ml[serving] not installed")
    statistical = run_benchmark(train, test, model="statistical", seed=1337)
    forest = run_benchmark(train, test, model="isolation_forest", seed=1337)
    assert statistical.model_name != forest.model_name
    assert statistical.params != forest.params


def test_isolation_forest_raises_model_unavailable_without_sklearn(
    dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    from sm_ml.errors import ModelUnavailable

    real_import = builtins.__import__

    def _blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name in ("sklearn", "sklearn.ensemble"):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    train, test = dataset
    with pytest.raises(ModelUnavailable, match="sm-ml\\[serving\\]"):
        run_benchmark(train, test, model="isolation_forest", seed=1337)


def test_unknown_model_name_raises(dataset) -> None:
    train, test = dataset
    with pytest.raises(ValueError, match="unknown model"):
        run_benchmark(train, test, model="not-a-real-model", seed=1337)  # type: ignore[arg-type]


def test_run_benchmark_raises_when_the_train_split_has_no_benign_rows(dataset) -> None:
    train, test = dataset
    all_attack_labels = tuple(1 for _ in train.labels)
    poisoned = train.__class__(
        dataset_id=train.dataset_id, sha256=train.sha256,
        feature_names=train.feature_names, rows=train.rows, labels=all_attack_labels,
    )
    with pytest.raises(ValueError, match="no benign rows"):
        run_benchmark(poisoned, test, seed=1337)
