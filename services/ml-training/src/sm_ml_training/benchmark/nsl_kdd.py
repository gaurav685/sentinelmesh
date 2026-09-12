"""NSL-KDD dataset adapter (`ml/datasets/nsl-kdd/MANIFEST.md`).

No dataset ships (ADR-024). `load_nsl_kdd(train_path, test_path)` reads two
real, locally-staged files and raises `FileNotFoundError` if either is
missing — it never substitutes a fixture or fabricates rows.

Categorical columns (`protocol_type`, `service`, `flag`) are one-hot encoded
against a vocabulary **derived from the train split itself** (sorted, so the
column order is deterministic), never a hardcoded list — a value the test
split has that the train split does not falls into an explicit
`<column>__unknown` bucket instead of silently being dropped or crashing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

__all__ = ["PREPROCESSING_VERSION", "BenchmarkDataset", "load_nsl_kdd"]

PREPROCESSING_VERSION = "nsl-kdd-v1"

# Column indices in the raw 42-column KDD record (0-indexed).
_CATEGORICAL_COLS: tuple[tuple[int, str], ...] = (
    (1, "protocol_type"),
    (2, "service"),
    (3, "flag"),
)
_CATEGORICAL_INDICES = frozenset(i for i, _ in _CATEGORICAL_COLS)
_LABEL_COL = 41
_N_FEATURE_COLS = 41  # columns 0..40; column 41 is the label, 42 is difficulty


@dataclass(frozen=True)
class BenchmarkDataset:
    dataset_id: str
    sha256: str
    feature_names: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]
    labels: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.rows) != len(self.labels):
            raise ValueError("rows and labels must be the same length")
        for r in self.rows:
            if len(r) != len(self.feature_names):
                raise ValueError(
                    f"row has {len(r)} values, expected {len(self.feature_names)}"
                )

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_anomalous(self) -> int:
        return sum(self.labels)


def _read_raw_rows(path: Path) -> list[list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"NSL-KDD file not found: {path}")
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < _LABEL_COL + 1:
            raise ValueError(f"malformed NSL-KDD row (only {len(parts)} columns): {line[:80]!r}")
        rows.append(parts)
    if not rows:
        raise ValueError(f"no rows read from {path}")
    return rows


def _build_vocab(train_rows: list[list[str]], col: int) -> tuple[str, ...]:
    return tuple(sorted({row[col] for row in train_rows}))


def _feature_names(vocabs: dict[int, tuple[str, ...]]) -> tuple[str, ...]:
    numeric = tuple(f"f{i}" for i in range(_N_FEATURE_COLS) if i not in _CATEGORICAL_INDICES)
    onehot: list[str] = []
    for col, name in _CATEGORICAL_COLS:
        for value in vocabs[col]:
            onehot.append(f"{name}={value}")
        onehot.append(f"{name}__unknown")
    return numeric + tuple(onehot)


def _encode_row(row: list[str], vocabs: dict[int, tuple[str, ...]]) -> tuple[float, ...]:
    numeric = tuple(
        float(row[i]) for i in range(_N_FEATURE_COLS) if i not in _CATEGORICAL_INDICES
    )
    onehot: list[float] = []
    for col, _name in _CATEGORICAL_COLS:
        vocab = vocabs[col]
        value = row[col]
        matched = False
        for candidate in vocab:
            onehot.append(1.0 if candidate == value else 0.0)
            matched = matched or candidate == value
        onehot.append(0.0 if matched else 1.0)  # __unknown
    return numeric + tuple(onehot)


def load_nsl_kdd(
    train_path: str | Path, test_path: str | Path
) -> tuple[BenchmarkDataset, BenchmarkDataset]:
    train_p, test_p = Path(train_path), Path(test_path)
    train_raw = _read_raw_rows(train_p)
    test_raw = _read_raw_rows(test_p)

    vocabs = {col: _build_vocab(train_raw, col) for col, _name in _CATEGORICAL_COLS}
    names = _feature_names(vocabs)

    train_rows = tuple(_encode_row(r, vocabs) for r in train_raw)
    train_labels = tuple(0 if r[_LABEL_COL] == "normal" else 1 for r in train_raw)
    test_rows = tuple(_encode_row(r, vocabs) for r in test_raw)
    test_labels = tuple(0 if r[_LABEL_COL] == "normal" else 1 for r in test_raw)

    train_sha = hashlib.sha256(train_p.read_bytes()).hexdigest()
    test_sha = hashlib.sha256(test_p.read_bytes()).hexdigest()

    train = BenchmarkDataset(
        dataset_id="nsl-kdd-train", sha256=train_sha,
        feature_names=names, rows=train_rows, labels=train_labels,
    )
    test = BenchmarkDataset(
        dataset_id="nsl-kdd-test", sha256=test_sha,
        feature_names=names, rows=test_rows, labels=test_labels,
    )
    return train, test
