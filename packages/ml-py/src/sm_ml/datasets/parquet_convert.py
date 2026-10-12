"""One-time CSV -> Parquet conversion for CICIDS2017 / UNSW-NB15.

Built after a real memory crisis: the row-based loaders in this package
(`cicids2017.load_cicids2017`, `unsw_nb15.load_unsw_nb15`) build a Python
tuple-of-floats per row. Measured with `psutil` against the real
downloaded files (not estimated): ~3.9 KB/row for CICIDS2017's ~80
features, ~4.2 KB/row for UNSW-NB15's 192-dimensional one-hot encoding.
A full-scope Phase 1 run (all real train/test files) drove this machine's
free RAM from ~6.5 GB to ~430 MB before being killed.

This module fixes the actual cause -- Python object overhead, not the
real data volume -- by converting once to Parquet with narrow dtypes
(`Float32` instead of `Float64`, `Categorical` for label-like columns) and
the leaky/identifier columns already dropped, using Polars' streaming
`scan_csv().sink_parquet()` so the conversion itself never materialises a
full CSV in memory regardless of file size. `sm_ml.datasets.arrays` reads
only the needed columns back out afterward, directly into float32 numpy
arrays -- no Python tuple-of-floats stage at all on the array path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .cicids2017 import _LEAKY_COLUMNS as _CICIDS_LEAKY
from .unsw_nb15 import _ATTACK_CAT_COLUMN, _CANONICAL_ATTACK_CAT, _read_feature_names
from .unsw_nb15 import _CATEGORICAL_COLUMNS as _UNSW_CATEGORICAL
from .unsw_nb15 import _LEAKY_COLUMNS as _UNSW_LEAKY

__all__ = ["convert_cicids2017_to_parquet", "convert_unsw_nb15_to_parquet"]

_CICIDS_LABEL_COLUMN = "Label"
_UNSW_LABEL_COLUMN = "Label"


def _require_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError(f"Parquet conversion needs sm-ml[datasets] (polars): {exc}") from exc
    return pl


def _clean_numeric_expr(pl: Any, col: str) -> Any:
    """Real-valued cast with the same NaN/Infinity/null -> 0.0 convention
    `cicids2017._to_float`/`unsw_nb15._to_float` already use -- a known,
    documented CICIDS2017/UNSW-NB15 artifact, not something new here."""
    e = pl.col(col).cast(pl.Float64, strict=False).fill_null(0.0)
    e = pl.when(e.is_finite()).then(e).otherwise(0.0)
    return e.cast(pl.Float32).alias(col)


def convert_cicids2017_to_parquet(raw_dir: Path, out_dir: Path, filenames: tuple[str, ...]) -> list[Path]:
    """Convert each named CICIDS2017 day file to `out_dir/<stem>.parquet`:
    leaky columns dropped, every feature column cast to Float32, `Label`
    kept as a plain string (Parquet dictionary-encodes it automatically --
    this dataset's real label cardinality is tiny, a handful of strings
    per file). Streamed end to end; never holds a full file in memory."""
    pl = _require_polars()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in filenames:
        src = raw_dir / name
        if not src.exists():
            raise FileNotFoundError(f"missing CICIDS2017 file: {src}")
        lf = pl.scan_csv(src, infer_schema_length=10_000, encoding="utf8-lossy")
        rename = {c: c.strip() for c in lf.collect_schema().names()}
        lf = lf.rename(rename)
        stripped = list(rename.values())
        if _CICIDS_LABEL_COLUMN not in stripped:
            raise ValueError(f"{src}: no {_CICIDS_LABEL_COLUMN!r} column found (columns: {stripped})")
        drop = {c for c in stripped if c in _CICIDS_LEAKY}
        feature_cols = sorted(c for c in stripped if c not in drop and c != _CICIDS_LABEL_COLUMN)
        lf = lf.select([
            *(_clean_numeric_expr(pl, c) for c in feature_cols),
            pl.col(_CICIDS_LABEL_COLUMN).str.strip_chars().alias("Label"),
        ])
        dest = out_dir / (Path(name).stem + ".parquet")
        lf.sink_parquet(dest, compression="zstd")
        written.append(dest)
    return written


def convert_unsw_nb15_to_parquet(raw_dir: Path, out_dir: Path, row_files: tuple[str, ...]) -> list[Path]:
    """Convert each named UNSW-NB15 row file to `out_dir/<stem>.parquet`:
    column names from `UNSW-NB15_features.csv` (the row files ship with no
    header), leaky columns dropped, numeric columns cast to Float32,
    `proto`/`state` kept as strings (one-hot encoding happens later, in
    `sm_ml.datasets.arrays`, against a train-only vocabulary -- baking a
    vocab into this one-time conversion would silently leak test-only
    categories into it), and `attack_cat` normalised through the one real
    spelling inconsistency the audit found (`"Backdoors"` -> `"Backdoor"`)
    so combining multiple row files never splits one real category into
    two."""
    pl = _require_polars()
    out_dir.mkdir(parents=True, exist_ok=True)
    features_path = raw_dir / "UNSW-NB15_features.csv"
    if not features_path.exists():
        raise FileNotFoundError(f"missing {features_path} -- the row files have no header; this is required")
    column_names = _read_feature_names(features_path, pl)
    missing_special = [
        c for c in (_UNSW_LABEL_COLUMN, _ATTACK_CAT_COLUMN, *_UNSW_CATEGORICAL) if c not in column_names
    ]
    if missing_special:
        raise ValueError(f"{features_path}: expected columns {missing_special} not found in {column_names}")
    numeric_cols = [
        c for c in column_names
        if c not in _UNSW_LEAKY and c not in _UNSW_CATEGORICAL
        and c not in (_UNSW_LABEL_COLUMN, _ATTACK_CAT_COLUMN)
    ]

    written: list[Path] = []
    for name in row_files:
        src = raw_dir / name
        if not src.exists():
            raise FileNotFoundError(f"missing UNSW-NB15 file: {src}")
        lf = pl.scan_csv(
            src, has_header=False, new_columns=column_names,
            infer_schema_length=10_000, encoding="utf8-lossy", ignore_errors=True,
        )
        attack_cat_stripped = pl.col(_ATTACK_CAT_COLUMN).cast(pl.Utf8).fill_null("").str.strip_chars()
        attack_cat_or_normal = (
            pl.when(attack_cat_stripped == "").then(pl.lit("Normal")).otherwise(attack_cat_stripped)
        )
        lf = lf.select([
            *(_clean_numeric_expr(pl, c) for c in numeric_cols),
            *(pl.col(c).cast(pl.Utf8).fill_null("").str.strip_chars().alias(c) for c in _UNSW_CATEGORICAL),
            pl.col(_UNSW_LABEL_COLUMN).cast(pl.Int8, strict=False).fill_null(0).alias("Label"),
            attack_cat_or_normal.replace(_CANONICAL_ATTACK_CAT).alias(_ATTACK_CAT_COLUMN),
        ])
        dest = out_dir / (Path(name).stem + ".parquet")
        lf.sink_parquet(dest, compression="zstd")
        written.append(dest)
    return written
