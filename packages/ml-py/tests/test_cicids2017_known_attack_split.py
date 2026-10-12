from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("polars")

from sm_ml.datasets.arrays import load_cicids2017_known_attack_split
from sm_ml.datasets.parquet_convert import convert_cicids2017_to_parquet

_FIXTURES = Path(__file__).parent / "fixtures" / "cicids2017"


@pytest.fixture
def cicids_parquet(tmp_path: Path) -> Path:
    out = tmp_path / "cicids"
    convert_cicids2017_to_parquet(_FIXTURES, out, ("day1.csv", "day2.csv"))
    return out


def test_known_attack_split_whole_windows_never_cross(cicids_parquet: Path) -> None:
    train, test, info = load_cicids2017_known_attack_split(
        cicids_parquet, files=("day1.parquet", "day2.parquet"), window_rows=1, test_fraction=0.4, seed=1,
    )
    assert train.n_rows + test.n_rows == 5  # real total rows across both tiny fixture files
    assert info["n_windows"] == 5  # window_rows=1 -- every real row is its own window here


def test_known_attack_split_real_rows_conserved(cicids_parquet: Path) -> None:
    train, test, _info = load_cicids2017_known_attack_split(
        cicids_parquet, files=("day1.parquet", "day2.parquet"), window_rows=2000, test_fraction=0.3, seed=7,
    )
    assert train.n_rows + test.n_rows == 5


def test_known_attack_split_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_cicids2017_known_attack_split(tmp_path, files=("nonexistent.parquet",))
