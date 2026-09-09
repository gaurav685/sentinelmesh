"""Robust statistical anomaly detector — MAD z-score. Standard library only.

Always available. It is the ADR-013 degraded path *and* a first-class detector:
`detection-engine` fits one per feature group from a rolling window (adaptive
thresholds, req 5) and scores every event against it.

For feature `x` with training median `m` and median-absolute-deviation `mad`:

    z = 0.6745 * (x - m) / mad          (mad below eps -> z = 0)

The event's score is `max(|z|)` over its features. `is_anomaly` is
`max(|z|) >= z_threshold` (default 3.5). The normalised score is a logistic
centred on the threshold, so it crosses 0.5 exactly at the verdict boundary.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sm_contracts import AnomalyMethod

from .base import AnomalyScore

__all__ = ["DEFAULT_Z_THRESHOLD", "StatisticalModel"]

DEFAULT_Z_THRESHOLD = 3.5
_MAD_TO_SIGMA = 0.6745
_EPS = 1e-9


def _mad(values: list[float], median: float) -> float:
    return statistics.median(abs(v - median) for v in values)


@dataclass(frozen=True)
class StatisticalModel:
    feature_names: tuple[str, ...]
    medians: dict[str, float]
    mads: dict[str, float]
    z_threshold: float = DEFAULT_Z_THRESHOLD
    method: AnomalyMethod = AnomalyMethod.mad_zscore
    model_version: str | None = None

    @classmethod
    def fit(
        cls,
        feature_names: Sequence[str],
        rows: list[list[float]],
        *,
        z_threshold: float = DEFAULT_Z_THRESHOLD,
    ) -> StatisticalModel:
        names = tuple(feature_names)
        if not rows:
            raise ValueError("StatisticalModel.fit needs at least one row")
        for r in rows:
            if len(r) != len(names):
                raise ValueError(f"row has {len(r)} values, expected {len(names)}")
        medians: dict[str, float] = {}
        mads: dict[str, float] = {}
        for i, name in enumerate(names):
            col = [r[i] for r in rows]
            med = statistics.median(col)
            medians[name] = med
            mads[name] = _mad(col, med)
        return cls(feature_names=names, medians=medians, mads=mads, z_threshold=z_threshold)

    def _zscores(self, features: Sequence[float]) -> dict[str, float]:
        if len(features) != len(self.feature_names):
            raise ValueError(
                f"expected {len(self.feature_names)} features, got {len(features)}"
            )
        z: dict[str, float] = {}
        for name, x in zip(self.feature_names, features, strict=True):
            mad = self.mads.get(name, 0.0)
            if mad <= _EPS:
                z[name] = 0.0
            else:
                z[name] = _MAD_TO_SIGMA * (x - self.medians.get(name, 0.0)) / mad
        return z

    def score(self, features: Sequence[float]) -> AnomalyScore:
        z = self._zscores(features)
        by_abs = sorted(z.items(), key=lambda kv: abs(kv[1]), reverse=True)
        max_z = abs(by_abs[0][1]) if by_abs else 0.0
        normalized = 1.0 / (1.0 + math.exp(-(max_z - self.z_threshold)))
        contributing = [name for name, val in by_abs if abs(val) >= self.z_threshold][:5]
        return AnomalyScore(
            method=self.method,
            score=max_z,
            normalized_score=min(1.0, max(0.0, normalized)),
            threshold=self.z_threshold,
            is_anomaly=max_z >= self.z_threshold,
            model_version=self.model_version,
            contributing_features=contributing,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "feature_names": list(self.feature_names),
            "medians": self.medians,
            "mads": self.mads,
            "z_threshold": self.z_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatisticalModel:
        return cls(
            feature_names=tuple(data["feature_names"]),
            medians=dict(data["medians"]),
            mads=dict(data["mads"]),
            z_threshold=float(data.get("z_threshold", DEFAULT_Z_THRESHOLD)),
        )
