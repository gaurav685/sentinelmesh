from __future__ import annotations

from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from sm_ml.datasets.unsw_nb15 import load_unsw_nb15  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "unsw_nb15"


def test_leaky_ip_columns_dropped_ports_kept() -> None:
    train, _test = load_unsw_nb15(
        FIXTURES, test_fraction=0.5, seed=1, row_files=("UNSW-NB15_1.csv",),
    )
    assert not any(f in ("srcip", "dstip") for f in train.feature_names)
    assert "sport" in train.feature_names
    assert "dsport" in train.feature_names


def test_categorical_encoding_and_unknown_bucket() -> None:
    train, _test = load_unsw_nb15(
        FIXTURES, test_fraction=0.5, seed=1, row_files=("UNSW-NB15_1.csv",),
    )
    assert any(f.startswith("proto=") for f in train.feature_names)
    assert any(f.startswith("state=") for f in train.feature_names)
    assert "proto=__unknown" in train.feature_names
    assert "state=__unknown" in train.feature_names


def test_attack_cat_never_a_feature_only_the_label() -> None:
    train, test = load_unsw_nb15(
        FIXTURES, test_fraction=0.5, seed=1, row_files=("UNSW-NB15_1.csv",),
    )
    assert "attack_cat" not in train.feature_names
    assert "Label" not in train.feature_names
    assert all(t in ("Normal", "Generic", "Exploits") for t in train.attack_types + test.attack_types)


def test_split_is_deterministic_for_a_fixed_seed() -> None:
    a_train, a_test = load_unsw_nb15(FIXTURES, test_fraction=0.5, seed=1, row_files=("UNSW-NB15_1.csv",))
    b_train, b_test = load_unsw_nb15(FIXTURES, test_fraction=0.5, seed=1, row_files=("UNSW-NB15_1.csv",))
    assert a_train.labels == b_train.labels
    assert a_test.labels == b_test.labels


def test_missing_features_file_raises_clearly() -> None:
    with pytest.raises(FileNotFoundError, match=r"UNSW-NB15_features\.csv"):
        load_unsw_nb15(Path("/nonexistent/dir/for/real"))
