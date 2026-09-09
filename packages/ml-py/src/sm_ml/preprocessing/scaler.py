"""Deterministic, versioned standardisation. Pure Python — no numpy.

`Preprocessor.fit` learns a per-feature mean and standard deviation from a set of
feature vectors; `transform` applies `(x - mean) / std`. A near-zero std is
replaced by 1 so a constant feature maps to 0 rather than blowing up. The fitted
state serialises to / from a plain dict for the model registry.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

__all__ = ["PREPROCESSING_VERSION", "Preprocessor"]

PREPROCESSING_VERSION = "1"

_EPS = 1e-9


@dataclass(frozen=True)
class Preprocessor:
    feature_names: tuple[str, ...]
    means: dict[str, float]
    stds: dict[str, float]
    version: str = field(default=PREPROCESSING_VERSION)

    @classmethod
    def fit(cls, feature_names: tuple[str, ...], rows: list[list[float]]) -> Preprocessor:
        if not rows:
            raise ValueError("Preprocessor.fit needs at least one row")
        n = len(feature_names)
        for r in rows:
            if len(r) != n:
                raise ValueError(f"row has {len(r)} values, expected {n}")
        means: dict[str, float] = {}
        stds: dict[str, float] = {}
        for i, name in enumerate(feature_names):
            col = [r[i] for r in rows]
            means[name] = statistics.fmean(col)
            stds[name] = statistics.pstdev(col) if len(col) > 1 else 0.0
        return cls(feature_names=tuple(feature_names), means=means, stds=stds)

    def transform(self, row: list[float]) -> list[float]:
        if len(row) != len(self.feature_names):
            raise ValueError(f"row has {len(row)} values, expected {len(self.feature_names)}")
        out: list[float] = []
        for name, x in zip(self.feature_names, row, strict=True):
            std = self.stds.get(name, 0.0)
            denom = std if std > _EPS else 1.0
            out.append((x - self.means.get(name, 0.0)) / denom)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "feature_names": list(self.feature_names),
            "means": self.means,
            "stds": self.stds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Preprocessor:
        return cls(
            feature_names=tuple(data["feature_names"]),
            means=dict(data["means"]),
            stds=dict(data["stds"]),
            version=str(data.get("version", PREPROCESSING_VERSION)),
        )
