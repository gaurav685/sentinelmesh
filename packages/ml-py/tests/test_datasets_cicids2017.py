from __future__ import annotations

from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from sm_ml.datasets.cicids2017 import load_cicids2017  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "cicids2017"


def test_leaky_columns_are_dropped_and_ports_kept() -> None:
    train, _test = load_cicids2017(FIXTURES, train_files=("day1.csv",), test_files=("day2.csv",))
    for leaky in ("Flow ID", "Source IP", "Destination IP", "Timestamp"):
        assert leaky not in train.feature_names
    for kept in ("Source Port", "Destination Port", "Protocol"):
        assert kept in train.feature_names


def test_label_and_attack_type_parsed_correctly() -> None:
    train, test = load_cicids2017(FIXTURES, train_files=("day1.csv",), test_files=("day2.csv",))
    assert train.labels == (0, 1, 0)
    assert train.attack_types == ("BENIGN", "PortScan", "BENIGN")
    assert test.labels == (0, 1)
    assert test.attack_types == ("BENIGN", "DDoS")


def test_day_split_never_mixes_files() -> None:
    train, test = load_cicids2017(FIXTURES, train_files=("day1.csv",), test_files=("day2.csv",))
    assert train.n_rows == 3
    assert test.n_rows == 2


def test_infinity_value_is_coerced_not_propagated() -> None:
    # day1's third row has Flow Duration=Infinity -- a real, documented
    # CICIDS2017 artifact; it must not become NaN/inf in the feature vector.
    train, _ = load_cicids2017(FIXTURES, train_files=("day1.csv",), test_files=("day2.csv",))
    for row in train.rows:
        for v in row:
            assert v == v  # not NaN
            assert v not in (float("inf"), float("-inf"))


def test_missing_train_file_raises_clearly() -> None:
    with pytest.raises(FileNotFoundError, match="missing CICIDS2017 file"):
        load_cicids2017(FIXTURES, train_files=("does-not-exist.csv",), test_files=("day2.csv",))


def test_missing_label_column_raises_clearly(tmp_path: Path) -> None:
    bad = tmp_path / "no_label.csv"
    bad.write_text("Flow ID,Source IP,Flow Duration\nabc,10.0.0.1,100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'Label' column"):
        load_cicids2017(tmp_path, train_files=("no_label.csv",), test_files=("no_label.csv",))
