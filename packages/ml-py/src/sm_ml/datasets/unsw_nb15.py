"""UNSW-NB15 adapter.

See `scripts/download_datasets.md` for the real source (official SharePoint
link, manual download -- not automated per the cloud-share rule) and exact
filenames.

Real, documented structure:

- The 4 row files (`UNSW-NB15_{1,2,3,4}.csv`) ship with **no header** --
  column names come only from `UNSW-NB15_features.csv` (its own `Name`
  column, in order). This loader fails clearly if that file is missing
  rather than guessing a column order.
- Leaky identifier columns dropped unconditionally: `srcip`, `dstip` (raw
  IP addresses). `sport`/`dsport` (ports) and `proto`/`state` (categorical)
  are kept as real features -- same reasoning as CICIDS2017's ports.
- `attack_cat` is the multi-class label (`''`/`'Normal'`-ish for benign,
  an attack-category string otherwise) and is used to populate
  `FlowDataset.attack_types` -- never kept as an input feature (it would
  let a classifier trivially memorise the label). `Label` (0/1) is the
  real binary ground truth, used directly rather than re-derived from
  `attack_cat`'s string value (its exact benign spelling has been
  inconsistent across UNSW-NB15 releases; `Label` has not been).
- **A real, verified spelling inconsistency in `attack_cat` across this
  mirror's own 4 row files**: `UNSW-NB15_1.csv` spells one category
  `"Backdoors"`; `UNSW-NB15_2/3/4.csv` spell the same real category
  `"Backdoor"` (confirmed by a real per-file value-count audit, not
  assumed). Loading only file 4 (as the reduced-scope Phase 1 run did)
  never hits this; loading multiple files together would otherwise split
  one real attack category into two `attack_types` buckets, corrupting
  `per_class_recall` and the held-out-attack-type selection.
  `_CANONICAL_ATTACK_CAT` normalises this -- the only such variant found
  by the audit; it is not a general fuzzy-matcher.
- `proto`/`state` are one-hot encoded against a vocabulary built from the
  TRAIN split only (`common.build_categorical_vocab`), with an
  `__unknown` bucket for a value only the test split has -- same
  convention as `sm_ml_training.benchmark.nsl_kdd`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import FlowDataset, LabelledRow, build_categorical_vocab, encode_categorical, file_sha256, split_indices

__all__ = ["load_unsw_nb15"]

_LEAKY_COLUMNS = frozenset({"srcip", "dstip"})
_CATEGORICAL_COLUMNS = ("proto", "state")
_LABEL_COLUMN = "Label"
_ATTACK_CAT_COLUMN = "attack_cat"
_ROW_FILES = ("UNSW-NB15_1.csv", "UNSW-NB15_2.csv", "UNSW-NB15_3.csv", "UNSW-NB15_4.csv")
# Real spelling variant found by auditing every row file's own attack_cat
# value counts (UNSW-NB15_1.csv alone uses "Backdoors"; _2/_3/_4 use
# "Backdoor" for the same real category) -- not a guess.
_CANONICAL_ATTACK_CAT = {"Backdoors": "Backdoor"}


def _canonical_attack_cat(value: str) -> str:
    return _CANONICAL_ATTACK_CAT.get(value, value)


def _require_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError(f"UNSW-NB15 loading needs sm-ml[datasets] (polars): {exc}") from exc
    return pl


def _read_feature_names(features_csv: Path, pl: Any) -> list[str]:
    frame = pl.read_csv(features_csv, infer_schema_length=10_000, encoding="utf8-lossy")
    cols = {c.strip().lower(): c for c in frame.columns}
    if "name" not in cols:
        raise ValueError(f"{features_csv}: expected a 'Name' column, found {frame.columns}")
    return [str(v).strip() for v in frame[cols["name"]].to_list()]


def _read_row_file(path: Path, column_names: list[str], pl: Any) -> Any:
    if len(column_names) < 1:
        raise ValueError("column_names is empty -- UNSW-NB15_features.csv parsed no rows")
    frame = pl.read_csv(
        path, has_header=False, new_columns=column_names,
        infer_schema_length=10_000, encoding="utf8-lossy", ignore_errors=True,
    )
    return frame


def _to_float(v: object) -> float:
    if v is None:
        return 0.0
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f


def load_unsw_nb15(
    data_dir: Path, *, test_fraction: float = 0.3, seed: int = 1337, row_files: tuple[str, ...] = _ROW_FILES,
) -> tuple[FlowDataset, FlowDataset]:
    """Load real UNSW-NB15 rows, concatenated across `row_files` (default:
    all 4 real parts), then a seeded random split (`common.split_indices`
    -- UNSW-NB15 has no capture-day field to split on, unlike CICIDS2017)."""
    pl = _require_polars()

    features_path = data_dir / "UNSW-NB15_features.csv"
    if not features_path.exists():
        raise FileNotFoundError(f"missing {features_path} -- the 4 row files have no header; this is required")
    column_names = _read_feature_names(features_path, pl)
    features_sha = file_sha256(features_path)

    numeric_cols = [
        c for c in column_names
        if c not in _LEAKY_COLUMNS and c not in _CATEGORICAL_COLUMNS
        and c not in (_LABEL_COLUMN, _ATTACK_CAT_COLUMN)
    ]
    missing_special = [c for c in (_LABEL_COLUMN, _ATTACK_CAT_COLUMN, *_CATEGORICAL_COLUMNS) if c not in column_names]
    if missing_special:
        raise ValueError(f"{features_path}: expected columns {missing_special} not found in {column_names}")

    raw_rows: list[dict[str, Any]] = []
    row_hashes: list[str] = []
    for name in row_files:
        path = data_dir / name
        if not path.exists():
            raise FileNotFoundError(f"missing UNSW-NB15 file: {path}")
        frame = _read_row_file(path, column_names, pl)
        raw_rows.extend(frame.to_dicts())
        row_hashes.append(file_sha256(path))

    if not raw_rows:
        raise ValueError("no rows loaded from the UNSW-NB15 row files")

    # Index-based split FIRST: the categorical vocab must be built from the
    # train rows only (never leak a test-only category into the encoding),
    # but every row (train and test) is encoded with that same vocab.
    idx_train, idx_test = split_indices(len(raw_rows), test_fraction=test_fraction, seed=seed)
    train_idx = set(idx_train)

    vocabs = {
        c: build_categorical_vocab(
            str(raw_rows[i].get(c) or "").strip() for i in range(len(raw_rows)) if i in train_idx
        )
        for c in _CATEGORICAL_COLUMNS
    }

    def _row_values(record: dict[str, Any]) -> tuple[float, ...]:
        numeric = tuple(_to_float(record.get(c)) for c in numeric_cols)
        cats: tuple[float, ...] = ()
        for c in _CATEGORICAL_COLUMNS:
            cats += encode_categorical(str(record.get(c) or "").strip(), vocabs[c])
        return numeric + cats

    full_rows = [
        LabelledRow(
            values=_row_values(record),
            label=1 if _to_float(record.get(_LABEL_COLUMN)) >= 1.0 else 0,
            attack_type=_canonical_attack_cat(str(record.get(_ATTACK_CAT_COLUMN) or "").strip() or "Normal"),
        )
        for record in raw_rows
    ]

    feature_names = tuple(numeric_cols) + tuple(
        f"{c}={v}" for c in _CATEGORICAL_COLUMNS for v in (*vocabs[c], "__unknown")
    )
    combined_sha = "+".join(sorted([features_sha, *row_hashes]))

    train_rows = [full_rows[i] for i in idx_train]
    test_rows = [full_rows[i] for i in idx_test]

    train = FlowDataset(
        dataset_id="unsw-nb15-train", sha256=combined_sha, feature_names=feature_names,
        rows=tuple(r.values for r in train_rows), labels=tuple(r.label for r in train_rows),
        attack_types=tuple(r.attack_type for r in train_rows),
    )
    test = FlowDataset(
        dataset_id="unsw-nb15-test", sha256=combined_sha, feature_names=feature_names,
        rows=tuple(r.values for r in test_rows), labels=tuple(r.label for r in test_rows),
        attack_types=tuple(r.attack_type for r in test_rows),
    )
    return train, test
