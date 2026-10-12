from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from sm_ml.datasets.parquet_convert import convert_cicids2017_to_parquet, convert_unsw_nb15_to_parquet

_CICIDS_FIXTURES = Path(__file__).parent / "fixtures" / "cicids2017"
_UNSW_FIXTURES = Path(__file__).parent / "fixtures" / "unsw_nb15"


def test_convert_cicids2017_drops_leaky_columns_and_casts_float32(tmp_path: Path) -> None:
    written = convert_cicids2017_to_parquet(_CICIDS_FIXTURES, tmp_path, ("day1.csv", "day2.csv"))
    assert len(written) == 2
    df = pl.read_parquet(written[0])
    for leaky in ("Flow ID", "Source IP", "Destination IP", "Timestamp"):
        assert leaky not in df.columns
    for numeric_col in ("Flow Duration", "Total Fwd Packets", "Total Backward Packets"):
        assert df.schema[numeric_col] == pl.Float32
    assert df.schema["Label"] == pl.String


def test_convert_cicids2017_cleans_infinity_to_zero(tmp_path: Path) -> None:
    written = convert_cicids2017_to_parquet(_CICIDS_FIXTURES, tmp_path, ("day1.csv",))
    df = pl.read_parquet(written[0])
    # day1's third row has "Infinity" in Flow Duration -- must become 0.0, not inf.
    row = df.filter(pl.col("Label") == "BENIGN").sort("Total Fwd Packets")[0]
    assert row["Flow Duration"][0] == 0.0


def test_convert_cicids2017_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        convert_cicids2017_to_parquet(_CICIDS_FIXTURES, tmp_path, ("nonexistent-day.csv",))


def test_convert_unsw_nb15_drops_leaky_and_normalises_backdoors(tmp_path: Path) -> None:
    written = convert_unsw_nb15_to_parquet(_UNSW_FIXTURES, tmp_path, ("UNSW-NB15_1.csv",))
    df = pl.read_parquet(written[0])
    assert "srcip" not in df.columns
    assert "dstip" not in df.columns
    assert df.schema["Label"] == pl.Int8
    assert df.schema["proto"] == pl.String
    # empty attack_cat -> "Normal", never left blank.
    normals = df.filter(pl.col("Label") == 0)
    assert set(normals["attack_cat"].to_list()) == {"Normal"}


def test_convert_unsw_nb15_missing_features_file_raises(tmp_path: Path) -> None:
    (tmp_path / "no_features_here").mkdir()
    with pytest.raises(FileNotFoundError):
        convert_unsw_nb15_to_parquet(tmp_path / "no_features_here", tmp_path / "out", ("UNSW-NB15_1.csv",))
