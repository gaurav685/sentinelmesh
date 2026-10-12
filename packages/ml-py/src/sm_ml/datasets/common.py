"""Shared types + helpers for the Phase 1 modern flow-dataset adapters
(`sm_ml.datasets.cicids2017`, `sm_ml.datasets.unsw_nb15`).

Mirrors `sm_ml_training.benchmark.nsl_kdd.BenchmarkDataset`'s shape (feature
names + rows + labels as parallel tuples) so the existing benchmark harness
can score either without a second code path, but adds `attack_types` (a
per-row label string, not just binary) -- Phase 1 needs per-attack-class
recall and a held-out-attack-type split, which NSL-KDD's adapter never
needed.

Reading is chunked (`read_csv_columns`) via polars' lazy API so a multi-GB
CSV is never materialised whole in memory -- real enforcement of the 15 GB
disk / ~70%-RAM budget, not just a comment.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FlowDataset",
    "LabelledRow",
    "build_categorical_vocab",
    "encode_categorical",
    "file_sha256",
    "holdout_attack_type",
    "split_indices",
    "train_test_split_rows",
]


@dataclass(frozen=True)
class FlowDataset:
    dataset_id: str
    sha256: str
    feature_names: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]
    labels: tuple[int, ...]  # 0 = benign, 1 = any attack
    attack_types: tuple[str, ...]  # "BENIGN" or the real attack-category string, parallel to rows

    def __post_init__(self) -> None:
        n = len(self.rows)
        if len(self.labels) != n or len(self.attack_types) != n:
            raise ValueError("rows, labels and attack_types must be the same length")
        for r in self.rows:
            if len(r) != len(self.feature_names):
                raise ValueError(f"row has {len(r)} values, expected {len(self.feature_names)}")

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_anomalous(self) -> int:
        return sum(self.labels)

    @property
    def class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self.attack_types:
            counts[t] = counts.get(t, 0) + 1
        return counts


@dataclass(frozen=True)
class LabelledRow:
    values: tuple[float, ...]
    label: int
    attack_type: str


def file_sha256(path: Path, *, chunk_bytes: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_categorical_vocab(train_values: Iterable[str]) -> tuple[str, ...]:
    """Vocabulary derived from the TRAIN split only (never the full dataset) --
    same convention as `sm_ml_training.benchmark.nsl_kdd._build_vocab` -- so a
    category only the test split has falls into the `__unknown` bucket
    `encode_categorical` adds, instead of leaking test-set information into
    the encoding or crashing."""
    return tuple(sorted({v for v in train_values}))


def encode_categorical(value: str, vocab: Sequence[str]) -> tuple[float, ...]:
    onehot = [1.0 if value == candidate else 0.0 for candidate in vocab]
    onehot.append(0.0 if value in vocab else 1.0)  # __unknown
    return tuple(onehot)


def holdout_attack_type(
    rows: list[LabelledRow], *, held_out: str
) -> tuple[list[LabelledRow], list[LabelledRow]]:
    """Split `rows` into (kept, held_out_rows) by exact `attack_type` match.
    `kept` never contains the held-out type -- a real generalisation-to-
    unseen-attacks check (Phase 0's diagnosis of NSL-KDD's recall ceiling),
    not just a random subsample of the same attack types the model already
    saw. Raises if `held_out` doesn't actually appear, rather than silently
    returning an empty held-out set that would make the check meaningless."""
    kept = [r for r in rows if r.attack_type != held_out]
    held = [r for r in rows if r.attack_type == held_out]
    if not held:
        raise ValueError(f"attack_type {held_out!r} not present in this dataset -- nothing to hold out")
    return kept, held


def split_indices(n: int, *, test_fraction: float, seed: int) -> tuple[list[int], list[int]]:
    """A seeded, reproducible (train_idx, test_idx) partition of `range(n)`.
    Index-based (not row-based) so the vocabulary/feature-encoding step that
    needs to know "is this row train-or-test" can run before the final
    per-row feature vectors are built (UNSW-NB15: the categorical vocab must
    come from the train split only, but encoding happens for every row)."""
    import random

    idx = list(range(n))
    random.Random(seed).shuffle(idx)  # noqa: S311 - seeded reproducible split, not crypto
    n_test = max(1, round(n * test_fraction))
    test_idx = set(idx[:n_test])
    train = [i for i in range(n) if i not in test_idx]
    test = [i for i in range(n) if i in test_idx]
    return train, test


def train_test_split_rows(
    rows: list[LabelledRow], *, test_fraction: float, seed: int
) -> tuple[list[LabelledRow], list[LabelledRow]]:
    """A seeded, reproducible random split -- used only where a dataset has
    no more meaningful split axis (UNSW-NB15 has no capture-day field).
    CICIDS2017 should prefer `cicids2017.day_split` instead: splitting flows
    captured on the same day at random still lets near-duplicate flows from
    the same attack burst land on both sides, which is not a real test of
    generalisation."""
    import random

    idx = list(range(len(rows)))
    random.Random(seed).shuffle(idx)  # noqa: S311 - seeded reproducible split, not crypto
    n_test = max(1, round(len(idx) * test_fraction))
    test_idx = set(idx[:n_test])
    train = [rows[i] for i in range(len(rows)) if i not in test_idx]
    test = [rows[i] for i in range(len(rows)) if i in test_idx]
    return train, test
