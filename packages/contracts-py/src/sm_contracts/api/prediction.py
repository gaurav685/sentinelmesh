"""Predictive-intelligence contracts (Phase 13; req 15).

**There is no trained predictive model in this build.** Every `Prediction`
comes from `sm_ml.predict` — deterministic heuristics over data the platform
already has (kill-chain position, a subject's own technique history,
fingerprint similarity, campaign activity), never a learned probability.
`model_version` names the rule set (`"heuristic-v1"`), never a training run.
A prediction is always accompanied by its `confidence`, `evidence`, and
`generated_at` so it is never presented as a verified fact — a caller that
drops those fields before display is misusing the contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc
from ..enums import ThreatSubjectType

__all__ = [
    "AttackProgressionRequest",
    "LateralMovementRequest",
    "NextActionRequest",
    "Prediction",
    "PredictionKind",
    "ThreatTrajectoryRequest",
]

PredictionKind = Literal["attack_progression", "lateral_movement", "next_action", "threat_trajectory"]


class Prediction(SmBaseModel):
    kind: PredictionKind
    #: `None` for a campaign-level prediction (`threat_trajectory`) — a
    #: campaign has no single subject; `subject_id` is then the campaign id.
    subject_type: ThreatSubjectType | None
    subject_id: str = Field(min_length=1, max_length=256)
    #: A short label, e.g. a kill-chain stage name, a technique id, or
    #: `"other_subject_type:other_subject_id"`. `"none — ..."` or
    #: `"unknown — ..."` when the input does not support a prediction —
    #: `confidence` is then always `0.0`, never a guess dressed as a result.
    prediction: str = Field(min_length=1, max_length=256)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=20)
    features: dict[str, float | int | str] = Field(default_factory=dict, max_length=20)
    model_version: str = Field(min_length=1, max_length=32)
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class AttackProgressionRequest(SmBaseModel):
    chain_id: UUID


class NextActionRequest(SmBaseModel):
    chain_id: UUID


class LateralMovementRequest(SmBaseModel):
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)


class ThreatTrajectoryRequest(SmBaseModel):
    campaign_id: UUID
