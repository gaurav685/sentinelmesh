from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sm_ml.datasets.arrays import load_cicids2017_arrays, load_unsw_nb15_arrays
from sm_ml.datasets.parquet_convert import convert_cicids2017_to_parquet, convert_unsw_nb15_to_parquet

_CICIDS_FIXTURES = Path(__file__).parent / "fixtures" / "cicids2017"
_UNSW_FIXTURES = Path(__file__).parent / "fixtures" / "unsw_nb15"


@pytest.fixture
def cicids_parquet(tmp_path: Path) -> Path:
    out = tmp_path / "cicids"
    convert_cicids2017_to_parquet(_CICIDS_FIXTURES, out, ("day1.csv", "day2.csv"))
    return out


@pytest.fixture
def unsw_parquet(tmp_path: Path) -> Path:
    out = tmp_path / "unsw"
    convert_unsw_nb15_to_parquet(_UNSW_FIXTURES, out, ("UNSW-NB15_1.csv",))
    return out


def test_load_cicids2017_arrays_is_float32(cicids_parquet: Path) -> None:
    train, test, info = load_cicids2017_arrays(
        cicids_parquet, train_files=("day1.parquet",), test_files=("day2.parquet",)
    )
    assert train.X.dtype == np.float32
    assert train.y.tolist() == [0, 1, 0]
    assert test.y.tolist() == [0, 1]
    assert info["benign_sample_fraction"] is None


def test_load_cicids2017_arrays_benign_sampling_keeps_all_attacks(cicids_parquet: Path) -> None:
    train, _test, info = load_cicids2017_arrays(
        cicids_parquet, train_files=("day1.parquet",), test_files=("day2.parquet",),
        benign_sample_fraction=0.5, seed=7,
    )
    # day1 has 1 attack row (PortScan) + 2 benign rows -- the attack row must survive sampling.
    assert int(train.y.sum()) == 1
    assert info["n_benign_total"] == 2


def test_load_cicids2017_arrays_test_split_never_sampled(cicids_parquet: Path) -> None:
    _train, test, _info = load_cicids2017_arrays(
        cicids_parquet, train_files=("day1.parquet",), test_files=("day2.parquet",),
        benign_sample_fraction=0.01, seed=7,
    )
    assert test.n_rows == 2  # day2's real row count, untouched regardless of train sampling


def test_load_cicids2017_arrays_column_mismatch_raises(tmp_path: Path) -> None:
    out1 = tmp_path / "a"
    convert_cicids2017_to_parquet(_CICIDS_FIXTURES, out1, ("day1.csv",))
    with pytest.raises(FileNotFoundError):
        load_cicids2017_arrays(out1, train_files=("day1.parquet",), test_files=("missing.parquet",))


def test_load_unsw_nb15_arrays_onehot_vocab_from_train_only(unsw_parquet: Path) -> None:
    train, test, _info = load_unsw_nb15_arrays(
        unsw_parquet, row_files=("UNSW-NB15_1.parquet",), test_fraction=0.5, seed=1
    )
    assert train.X.dtype == np.float32
    assert any(f.startswith("proto=") for f in train.feature_names)
    assert any(f.endswith("__unknown") for f in train.feature_names)
    assert train.feature_names == test.feature_names


def test_load_unsw_nb15_arrays_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_unsw_nb15_arrays(tmp_path, row_files=("nonexistent.parquet",))
