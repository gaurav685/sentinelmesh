"""Float32-numpy-native loaders reading from `parquet_convert`'s output.

No Python tuple-of-floats stage anywhere on this path -- `FlowDataset`
(used by `cicids2017.load_cicids2017`/`unsw_nb15.load_unsw_nb15`, and by
their existing tests) builds one Python object per feature value, which
measured (via `psutil`, against the real downloaded files) at ~3.9-4.2
KB/row. A Polars DataFrame of `Float32` columns stays columnar end to
end, and `DataFrame.to_numpy()` on an all-`Float32` frame returns a
`float32` ndarray directly (verified: no silent upcast to float64) -- 4
bytes/value, full stop. This module is the array-native counterpart to
`cicids2017`/`unsw_nb15`; those two stay as they are (small-fixture tests,
the subset smoke test) and are not replaced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import file_sha256, split_indices

__all__ = ["ArrayFlowDataset", "load_cicids2017_arrays", "load_unsw_nb15_arrays"]


def _require_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError(f"array loading needs sm-ml[datasets] (polars): {exc}") from exc
    return pl


@dataclass(frozen=True)
class ArrayFlowDataset:
    dataset_id: str
    sha256: str
    feature_names: tuple[str, ...]
    X: Any  # numpy.ndarray, float32, shape (n_rows, n_features)
    y: Any  # numpy.ndarray, int8, shape (n_rows,)
    attack_types: tuple[str, ...]

    @property
    def n_rows(self) -> int:
        return int(self.X.shape[0])

    @property
    def n_anomalous(self) -> int:
        return int(self.y.sum())


def load_cicids2017_arrays(
    parquet_dir: Path,
    *,
    train_files: tuple[str, ...],
    test_files: tuple[str, ...],
    benign_sample_fraction: float | None = None,
    seed: int = 1337,
) -> tuple[ArrayFlowDataset, ArrayFlowDataset, dict[str, Any]]:
    """Read CICIDS2017 Parquet files (`parquet_convert.convert_cicids2017_to_parquet`'s
    output). If `benign_sample_fraction` is given, it applies ONLY to the
    train split's real `BENIGN` rows (every real attack row is kept, same
    as the row-based loader's benign-only-fit convention elsewhere in this
    package) -- the test split is never resampled, loaded and scored
    exactly as downloaded, so no evaluation metric here is ever computed
    on resampled data. `info` records the real counts, not an assumed
    ratio."""
    pl = _require_polars()

    def _load_frame(names: tuple[str, ...]) -> tuple[Any, list[str], list[str]]:
        feat_cols: list[str] | None = None
        hashes: list[str] = []
        frames = []
        for name in names:
            path = parquet_dir / name
            if not path.exists():
                raise FileNotFoundError(f"missing CICIDS2017 parquet file: {path}")
            cols = sorted(c for c in pl.scan_parquet(path).collect_schema().names() if c != "Label")
            if feat_cols is None:
                feat_cols = cols
            elif cols != feat_cols:
                raise ValueError(f"{path}: column set {cols} differs from the first file's {feat_cols}")
            frames.append(pl.scan_parquet(path))
            hashes.append(file_sha256(path))
        if feat_cols is None:
            raise ValueError("no files given")
        combined = pl.concat(frames, how="vertical").collect()
        return combined, feat_cols, hashes

    train_df, feat_cols, train_hashes = _load_frame(train_files)
    test_df, test_feat_cols, test_hashes = _load_frame(test_files)
    if test_feat_cols != feat_cols:
        raise ValueError(f"train/test column sets differ: {feat_cols} vs {test_feat_cols}")

    info: dict[str, Any] = {"benign_sample_fraction": benign_sample_fraction}
    if benign_sample_fraction is not None:
        attack_rows = train_df.filter(pl.col("Label") != "BENIGN")
        benign_rows = train_df.filter(pl.col("Label") == "BENIGN")
        n_benign_total = benign_rows.height
        benign_sampled = benign_rows.sample(fraction=benign_sample_fraction, seed=seed, with_replacement=False)
        info["n_benign_total"] = n_benign_total
        info["n_benign_sampled"] = benign_sampled.height
        train_df = pl.concat([attack_rows, benign_sampled], how="vertical").sample(fraction=1.0, seed=seed)
    else:
        info["n_benign_total"] = info["n_benign_sampled"] = train_df.filter(pl.col("Label") == "BENIGN").height

    def _to_array(df: Any, feature_cols: list[str], sha_parts: list[str]) -> ArrayFlowDataset:
        x = df.select(feature_cols).to_numpy()
        y = (df["Label"] != "BENIGN").cast(pl.Int8).to_numpy()
        return ArrayFlowDataset(
            dataset_id="cicids2017", sha256="+".join(sorted(sha_parts)),
            feature_names=tuple(feature_cols), X=x, y=y, attack_types=tuple(df["Label"].to_list()),
        )

    return _to_array(train_df, feat_cols, train_hashes), _to_array(test_df, feat_cols, test_hashes), info


def load_unsw_nb15_arrays(
    parquet_dir: Path,
    *,
    row_files: tuple[str, ...],
    test_fraction: float = 0.3,
    seed: int = 1337,
) -> tuple[ArrayFlowDataset, ArrayFlowDataset, dict[str, Any]]:
    """Read UNSW-NB15 Parquet files (`parquet_convert.convert_unsw_nb15_to_parquet`'s
    output). `proto`/`state` are one-hot encoded with Polars expressions
    (vectorised -- no Python per-row loop, unlike `unsw_nb15.encode_categorical`)
    against a vocabulary built from the TRAIN split only, with an
    `__unknown` bucket for a test-only category, same convention as the
    row-based loader."""
    pl = _require_polars()
    for f in row_files:
        if not (parquet_dir / f).exists():
            raise FileNotFoundError(f"missing UNSW-NB15 parquet file: {parquet_dir / f}")
    hashes = [file_sha256(parquet_dir / f) for f in row_files]
    full = pl.concat([pl.scan_parquet(parquet_dir / f) for f in row_files], how="vertical").collect()
    n = full.height
    idx_train, idx_test = split_indices(n, test_fraction=test_fraction, seed=seed)
    train_df = full[idx_train]
    test_df = full[idx_test]
    numeric_cols = sorted(c for c in full.columns if c not in ("proto", "state", "Label", "attack_cat"))
    del full

    vocabs = {c: sorted(v for v in train_df[c].unique().to_list() if v is not None) for c in ("proto", "state")}

    def _onehot_exprs(col: str) -> list[Any]:
        vocab = vocabs[col]
        return [
            *((pl.col(col) == v).cast(pl.Float32).alias(f"{col}={v}") for v in vocab),
            (~pl.col(col).is_in(vocab)).cast(pl.Float32).alias(f"{col}=__unknown"),
        ]

    feature_names = tuple(numeric_cols) + tuple(
        f"{c}={v}" for c in ("proto", "state") for v in (*vocabs[c], "__unknown")
    )

    def _to_array(df: Any) -> ArrayFlowDataset:
        # y/attack_types extracted BEFORE the one-hot select so `df` can be
        # dropped by the caller right after this call returns -- the
        # one-shot `.select()` below (numeric cols + onehot exprs together)
        # also avoids an earlier real mistake: building a full `with_columns`
        # intermediate (every original column plus every onehot column, ~210
        # columns resident at once) before narrowing with a second `.select()`.
        # Found by measuring real RSS against the full 4-file UNSW-NB15 load
        # (not assumed) -- peak RSS was high enough to trip the 3 GB free-
        # memory floor on this machine.
        y = df["Label"].cast(pl.Int8).to_numpy()
        attack_types = tuple(df["attack_cat"].to_list())
        x = df.select([
            *(pl.col(c) for c in numeric_cols), *_onehot_exprs("proto"), *_onehot_exprs("state"),
        ]).to_numpy()
        return ArrayFlowDataset(
            dataset_id="unsw-nb15", sha256="+".join(sorted(hashes)),
            feature_names=feature_names, X=x, y=y, attack_types=attack_types,
        )

    train_array = _to_array(train_df)
    del train_df
    test_array = _to_array(test_df)
    del test_df
    return train_array, test_array, {}
