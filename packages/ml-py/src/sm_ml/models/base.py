"""The anomaly-model interface.

`AnomalyModel` is what `detection-engine` and `ml-inference` program against.
Every implementation returns an `AnomalyScore` — a raw score, a score normalised
to [0, 1], the threshold in force, the boolean verdict, and which features drove
it. Nothing here claims a model is accurate; that requires an evaluation run
(ADR-024, `ml/models/*/CONTRACT.md`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sm_contracts import AnomalyMethod

from ..errors import ModelError, ModelNotTrained, ModelUnavailable

__all__ = [
    "AnomalyModel",
    "AnomalyScore",
    "ModelError",
    "ModelNotTrained",
    "ModelUnavailable",
]


@dataclass(frozen=True)
class AnomalyScore:
    method: AnomalyMethod
    score: float
    """Raw score in the method's own units (higher = more anomalous)."""
    normalized_score: float
    """`score` mapped to [0, 1]."""
    threshold: float
    is_anomaly: bool
    model_version: str | None = None
    contributing_features: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.normalized_score <= 1.0:
            raise ValueError("normalized_score must be in [0, 1]")


@runtime_checkable
class AnomalyModel(Protocol):
    @property
    def method(self) -> AnomalyMethod: ...

    @property
    def model_version(self) -> str | None: ...

    def score(self, features: Sequence[float]) -> AnomalyScore: ...
