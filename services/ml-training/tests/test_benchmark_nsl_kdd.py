from __future__ import annotations

from pathlib import Path

import pytest
from sm_ml_training.benchmark.nsl_kdd import load_nsl_kdd

# Real NSL-KDD row shape (42 comma-separated columns, no header): 38 numeric
# columns + protocol_type/service/flag (categorical) + attack_type + difficulty.
_TRAIN_ROWS = [
    "0,tcp,ftp_data,SF,491,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,2,0.00,0.00,0.00,0.00,1.00,0.00,0.00,150,25,0.17,0.03,0.17,0.00,0.00,0.00,0.05,0.00,normal,20",
    "0,udp,other,SF,146,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,13,1,0.00,0.00,0.00,0.00,0.08,0.15,0.00,255,1,0.00,0.60,0.88,0.00,0.00,0.00,0.00,0.00,normal,15",
    "0,tcp,private,S0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,123,6,1.00,1.00,0.00,0.00,0.05,0.07,0.00,255,26,0.10,0.05,0.00,0.00,1.00,1.00,0.00,0.00,neptune,19",
    "0,tcp,http,SF,300,200,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,5,5,0.00,0.00,0.00,0.00,1.00,0.00,0.00,10,10,0.00,0.00,0.00,0.00,0.00,0.00,0.00,0.00,normal,21",
]
_TEST_ROWS = [
    # same categories seen in train
    "0,tcp,http,SF,280,190,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,6,6,0.00,0.00,0.00,0.00,1.00,0.00,0.00,12,12,0.00,0.00,0.00,0.00,0.00,0.00,0.00,0.00,normal,21",
    # a category NEVER seen in train (icmp / ecr_i / SF-not-in-train combo) -> unknown bucket
    "0,icmp,ecr_i,SF,1032,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,511,511,0.00,0.00,1.00,1.00,0.00,0.00,0.00,255,255,1.00,0.00,1.00,0.00,0.00,0.00,0.00,0.00,smurf,21",
]


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    train = tmp_path / "KDDTrain+.txt"
    test = tmp_path / "KDDTest+.txt"
    train.write_text("\n".join(_TRAIN_ROWS) + "\n", encoding="utf-8")
    test.write_text("\n".join(_TEST_ROWS) + "\n", encoding="utf-8")
    return train, test


def test_load_returns_the_right_row_and_label_counts(files: tuple[Path, Path]) -> None:
    train, test = load_nsl_kdd(*files)
    assert train.n_rows == 4
    assert train.n_anomalous == 1  # only the "neptune" row
    assert test.n_rows == 2
    assert test.n_anomalous == 1  # only the "smurf" row


def test_train_and_test_share_the_same_feature_space(files: tuple[Path, Path]) -> None:
    train, test = load_nsl_kdd(*files)
    assert train.feature_names == test.feature_names
    assert len(train.rows[0]) == len(train.feature_names)
    assert len(test.rows[0]) == len(train.feature_names)


def test_vocabulary_is_derived_from_train_and_test_gets_an_unknown_bucket(
    files: tuple[Path, Path],
) -> None:
    train, test = load_nsl_kdd(*files)
    assert "protocol_type=tcp" in train.feature_names
    assert "protocol_type=udp" in train.feature_names
    assert "protocol_type__unknown" in train.feature_names
    assert "protocol_type=icmp" not in train.feature_names  # never in train

    icmp_row_idx = 1  # the smurf/icmp row
    unknown_col = train.feature_names.index("protocol_type__unknown")
    assert test.rows[icmp_row_idx][unknown_col] == 1.0
    tcp_col = train.feature_names.index("protocol_type=tcp")
    assert test.rows[icmp_row_idx][tcp_col] == 0.0

    known_row_idx = 0  # the http row, protocol_type=tcp is in the train vocab
    assert test.rows[known_row_idx][unknown_col] == 0.0
    assert test.rows[known_row_idx][tcp_col] == 1.0


def test_sha256_is_the_real_file_bytes(files: tuple[Path, Path]) -> None:
    import hashlib

    train_path, _test_path = files
    train, _test = load_nsl_kdd(*files)
    assert train.sha256 == hashlib.sha256(train_path.read_bytes()).hexdigest()


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_nsl_kdd(tmp_path / "nope-train.txt", tmp_path / "nope-test.txt")


def test_malformed_row_raises(tmp_path: Path) -> None:
    train = tmp_path / "train.txt"
    test = tmp_path / "test.txt"
    train.write_text("too,few,columns\n", encoding="utf-8")
    test.write_text(_TEST_ROWS[0] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        load_nsl_kdd(train, test)
