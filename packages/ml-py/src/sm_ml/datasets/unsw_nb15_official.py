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
- `training-set` has 82,332 real rows; `testing-set` has 175,341 -- yes,
  the official "testing" file is more than twice the size of "training"
  (a real, documented UNSW-NB15 quirk, not a bug in this loader).
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


def load_unsw_nb15_official_split(data_dir: Path) -> tuple[ArrayFlowDataset, ArrayFlowDataset, dict[str, Any]]:
    """Load the real official train/test partition. Returns
    `(train, test, info)` where `info["feature_columns"]` is the exact
    real list used (for the leakage audit: confirm no identifier/IP/port/
    timestamp column ever appears in it) and `info["onehot_vocab"]` is
    the real train-only categorical vocabulary (so held-out-type and
    ablation re-runs can reuse the identical encoding, not refit it)."""
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

    train_df = _read(train_path)
    test_df = _read(test_path)
    train_sha = file_sha256(train_path)
    test_sha = file_sha256(test_path)

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
    info: dict[str, Any] = {
        "feature_columns": list(feat_cols),
        "numeric_columns": list(numeric_cols),
        "categorical_columns": list(_CATEGORICAL_COLUMNS),
        "onehot_vocab": {c: list(v) for c, v in vocabs.items()},
        "train_sha256": train_sha,
        "test_sha256": test_sha,
    }
    return train, test, info
