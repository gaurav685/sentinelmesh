"""UNSW-NB15's official train/test partition
(`UNSW_NB15_training-set.csv` / `UNSW_NB15_testing-set.csv`), the
authors' own split -- not the random 2-of-4-row-file split
`unsw_nb15.load_unsw_nb15`/`arrays.load_unsw_nb15_arrays` use.

Real, documented structure (confirmed by reading the real header, not
assumed from a paper):

- 45 columns total: `id`, 42 real features, `attack_cat`, `label`.
- **No `srcip`/`dstip`/`sport`/`dsport`/`Stime`/`Ltime` at all** -- this
  release never included them, unlike the 4 raw row files. `id` (a plain
  row counter) is the only identifier-shaped column, and it is dropped.
- 3 categorical columns, not 2: `proto` (131 real distinct values),
  `service` (13, including the literal string `"-"` for "unknown/none"),
  `state` (7).
- **A real file-naming/content mismatch in this mirror, verified by
  counting real rows, not assumed**: the dataset's own documented
  convention (Moustafa & Slay; the UNSW-NB15 project page; the Kaggle
  listing's own description) is 175,341 real rows in the TRAINING
  partition and 82,332 in the TESTING partition. On this mirror,
  `UNSW_NB15_training-set.csv` physically has 82,332 rows and
  `UNSW_NB15_testing-set.csv` has 175,341 -- the two files' CONTENTS are
  swapped relative to their FILENAMES. `load_unsw_nb15_official_split`'s
  default `orientation="standard"` picks train/test BY REAL ROW COUNT
  (whichever file actually has ~175,341 rows becomes train), not by
  filename, matching the documented convention regardless of which
  physical file a given mirror copy happens to name which way.
  `orientation="literal"` reproduces this mirror's own (reversed)
  filenames as-is, kept only as a labelled secondary comparison.
- Both files are small enough (≤175K rows, ≤45 columns) to load directly
  with Polars' eager `read_csv` -- no streaming/Parquet-conversion step
  needed, unlike the 4 raw row files at ~2.5M rows total.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .arrays import ArrayFlowDataset
from .common import build_categorical_vocab, file_sha256
from .unsw_nb15 import _CANONICAL_ATTACK_CAT

__all__ = ["TEST_FILE", "TRAIN_FILE", "load_unsw_nb15_official_split"]

TRAIN_FILE = "UNSW_NB15_training-set.csv"
TEST_FILE = "UNSW_NB15_testing-set.csv"

_ID_COLUMN = "id"
_LABEL_COLUMN = "label"
_ATTACK_CAT_COLUMN = "attack_cat"
_CATEGORICAL_COLUMNS = ("proto", "service", "state")


def _require_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError(f"UNSW-NB15 official-split loading needs sm-ml[datasets] (polars): {exc}") from exc
    return pl


def feature_columns(data_dir: Path) -> tuple[str, ...]:
    """The real, complete list of feature columns this loader uses --
    every column except `id` (row counter), `attack_cat` (the multi-class
    label), and `label` (the real binary ground truth). Read from the
    real file header, not hardcoded, so it can never silently drift from
    what's actually in the CSV."""
    pl = _require_polars()
    cols = pl.scan_csv(data_dir / TRAIN_FILE, n_rows=1).collect_schema().names()
    cols = [c.strip().lstrip("﻿") for c in cols]
    return tuple(c for c in cols if c not in (_ID_COLUMN, _ATTACK_CAT_COLUMN, _LABEL_COLUMN))


_DOCUMENTED_TRAIN_ROWS = 175_341  # Moustafa & Slay's own published partition sizes
_DOCUMENTED_TEST_ROWS = 82_332


def load_unsw_nb15_official_split(
    data_dir: Path, *, orientation: str = "standard",
) -> tuple[ArrayFlowDataset, ArrayFlowDataset, dict[str, Any]]:
    """Load the real official train/test partition. `orientation="standard"`
    (the default) assigns train/test BY REAL ROW COUNT against the
    documented 175,341-train/82,332-test convention, not by filename --
    this mirror's `training-set.csv`/`testing-set.csv` contents are
    swapped relative to their names (verified: 82,332 rows in the file
    named "training", 175,341 in the one named "testing"). Pass
    `orientation="literal"` to reproduce this mirror's own (reversed)
    filenames as-is instead, kept only for a labelled secondary
    comparison against the standard-orientation primary result. Returns
    `(train, test, info)` where `info["feature_columns"]` is the exact
    real list used (for the leakage audit: confirm no identifier/IP/port/
    timestamp column ever appears in it), `info["onehot_vocab"]` is the
    real train-only categorical vocabulary, and `info["swapped_vs_filename"]`
    records whether this call actually swapped the two physical files."""
    if orientation not in ("standard", "literal"):
        raise ValueError(f"orientation must be 'standard' or 'literal', got {orientation!r}")
    pl = _require_polars()
    train_path = data_dir / TRAIN_FILE
    test_path = data_dir / TEST_FILE
    if not train_path.exists():
        raise FileNotFoundError(f"missing {train_path}")
    if not test_path.exists():
        raise FileNotFoundError(f"missing {test_path}")

    def _read(path: Path) -> Any:
        df = pl.read_csv(path, infer_schema_length=10_000, encoding="utf8")
        df = df.rename({c: c.strip().lstrip("﻿") for c in df.columns})
        return df

    file_a = _read(train_path)  # the file literally named "...training-set.csv"
    file_b = _read(test_path)  # the file literally named "...testing-set.csv"
    sha_a = file_sha256(train_path)
    sha_b = file_sha256(test_path)

    swapped = False
    if orientation == "standard":
        a_is_train = abs(file_a.height - _DOCUMENTED_TRAIN_ROWS) <= abs(file_b.height - _DOCUMENTED_TRAIN_ROWS)
        if a_is_train:
            train_df, test_df, train_sha, test_sha = file_a, file_b, sha_a, sha_b
        else:
            train_df, test_df, train_sha, test_sha = file_b, file_a, sha_b, sha_a
            swapped = True
    else:
        train_df, test_df, train_sha, test_sha = file_a, file_b, sha_a, sha_b

    feat_cols = feature_columns(data_dir)
    numeric_cols = tuple(c for c in feat_cols if c not in _CATEGORICAL_COLUMNS)

    vocabs = {c: build_categorical_vocab(train_df[c].cast(pl.Utf8).to_list()) for c in _CATEGORICAL_COLUMNS}

    def _onehot_exprs(col: str) -> list[Any]:
        vocab = vocabs[col]
        return [
            *((pl.col(col).cast(pl.Utf8) == v).cast(pl.Float32).alias(f"{col}={v}") for v in vocab),
            (~pl.col(col).cast(pl.Utf8).is_in(vocab)).cast(pl.Float32).alias(f"{col}=__unknown"),
        ]

    feature_names = tuple(numeric_cols) + tuple(
        f"{c}={v}" for c in _CATEGORICAL_COLUMNS for v in (*vocabs[c], "__unknown")
    )

    def _to_array(df: Any, sha: str) -> ArrayFlowDataset:
        y = df[_LABEL_COLUMN].cast(pl.Int8).to_numpy()
        attack_types = tuple(
            _CANONICAL_ATTACK_CAT.get(v, v) for v in df[_ATTACK_CAT_COLUMN].cast(pl.Utf8).to_list()
        )
        x = df.select([
            *(pl.col(c).cast(pl.Float32) for c in numeric_cols),
            *(e for c in _CATEGORICAL_COLUMNS for e in _onehot_exprs(c)),
        ]).to_numpy()
        return ArrayFlowDataset(
            dataset_id="unsw-nb15-official", sha256=sha, feature_names=feature_names, X=x, y=y,
            attack_types=attack_types,
        )

    train = _to_array(train_df, train_sha)
    test = _to_array(test_df, test_sha)
    n_train_anomalous = int(train.y.sum())
    n_test_anomalous = int(test.y.sum())
    info: dict[str, Any] = {
        "orientation": orientation,
        "swapped_vs_filename": swapped,
        "feature_columns": list(feat_cols),
        "numeric_columns": list(numeric_cols),
        "categorical_columns": list(_CATEGORICAL_COLUMNS),
        "onehot_vocab": {c: list(v) for c, v in vocabs.items()},
        "train_sha256": train_sha,
        "test_sha256": test_sha,
        "n_train": train.n_rows,
        "n_train_anomalous": n_train_anomalous,
        "train_attack_prevalence": round(n_train_anomalous / train.n_rows, 6),
        "n_test": test.n_rows,
        "n_test_anomalous": n_test_anomalous,
        "test_attack_prevalence": round(n_test_anomalous / test.n_rows, 6),
    }
    return train, test, info
