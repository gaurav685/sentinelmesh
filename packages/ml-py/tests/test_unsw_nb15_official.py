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
