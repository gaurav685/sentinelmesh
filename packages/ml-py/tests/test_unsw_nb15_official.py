from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("polars")

from sm_ml.datasets.unsw_nb15_official import feature_columns, load_unsw_nb15_official_split

_FIXTURES = Path(__file__).parent / "fixtures" / "unsw_nb15_official"


def test_feature_columns_excludes_id_attack_cat_label() -> None:
    cols = feature_columns(_FIXTURES)
    assert "id" not in cols
    assert "attack_cat" not in cols
    assert "label" not in cols
    assert "dur" in cols
    assert "proto" in cols


def test_feature_columns_has_no_ip_port_or_time_columns() -> None:
    # Exact names only -- "ct_src_dport_ltm" (an aggregate count feature) is
    # real signal and must not be flagged just for containing "dport"/"ltm"
    # as a substring of a legitimate compound name.
    cols = {c.lower() for c in feature_columns(_FIXTURES)}
    leaky_exact = {"srcip", "dstip", "sport", "dsport", "stime", "ltime", "flow id", "flow_id", "id"}
    assert cols.isdisjoint(leaky_exact)


def test_load_unsw_nb15_official_split_real_counts() -> None:
    train, test, info = load_unsw_nb15_official_split(_FIXTURES)
    assert train.n_rows == 4
    assert test.n_rows == 2
    assert int(train.y.sum()) == 2
    assert int(test.y.sum()) == 1
    assert "proto" in info["categorical_columns"]
    assert "service" in info["categorical_columns"]
    assert "state" in info["categorical_columns"]


def test_load_unsw_nb15_official_split_onehot_vocab_from_train_only() -> None:
    train, test, info = load_unsw_nb15_official_split(_FIXTURES)
    # test file's "sctp" proto value is NOT in train's vocab -- must fall into __unknown.
    assert "sctp" not in info["onehot_vocab"]["proto"]
    assert any(f == "proto=__unknown" for f in train.feature_names)
    assert train.feature_names == test.feature_names


def test_load_unsw_nb15_official_split_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_unsw_nb15_official_split(tmp_path)


_REVERSED_FIXTURES = Path(__file__).parent / "fixtures" / "unsw_nb15_official_reversed"


def test_load_unsw_nb15_official_split_standard_orientation_swaps_by_row_count() -> None:
    # This fixture mirrors the REAL mrwellsdavid/unsw-nb15 mirror: the file
    # named "training-set.csv" has fewer rows than "testing-set.csv" --
    # the real-world reversed case this loader exists to correct.
    train, test, info = load_unsw_nb15_official_split(_REVERSED_FIXTURES, orientation="standard")
    assert info["swapped_vs_filename"] is True
    assert train.n_rows == 4  # the physically-named "testing-set.csv" file, picked as train
    assert test.n_rows == 2


def test_load_unsw_nb15_official_split_literal_orientation_keeps_filenames() -> None:
    train, test, info = load_unsw_nb15_official_split(_REVERSED_FIXTURES, orientation="literal")
    assert info["swapped_vs_filename"] is False
    assert train.n_rows == 2  # the physically-named "training-set.csv" file, used as-is
    assert test.n_rows == 4


def test_load_unsw_nb15_official_split_reports_attack_prevalence() -> None:
    _train, _test, info = load_unsw_nb15_official_split(_REVERSED_FIXTURES, orientation="standard")
    assert info["n_train"] == 4
    assert info["n_test"] == 2
    assert info["train_attack_prevalence"] == pytest.approx(3 / 4)
    assert info["test_attack_prevalence"] == pytest.approx(0.0)


def test_load_unsw_nb15_official_split_invalid_orientation_raises() -> None:
    with pytest.raises(ValueError, match="orientation"):
        load_unsw_nb15_official_split(_REVERSED_FIXTURES, orientation="sideways")
