"""Detection-domain entity contracts (safe DTOs — Phase 5).

The `detection-engine` maps its Postgres rows to these before returning them over
the API. They are not the database models.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from ..common import TenantScoped, TimestampedModel, to_utc
from ..detection import EvidenceItem
from ..enums import (
    AlertStatus,
    AnomalyMethod,
    DetectionStatus,
    DetectorKind,
    ScoringStatus,
    Severity,
    ThreatSubjectType,
)
from ..telemetry import EntityRef

__all__ = ["Anomaly", "Detection", "SecurityAlert", "ThreatScore"]


class Anomaly(TenantScoped, TimestampedModel):
    """One scored feature vector. An anomaly is *evidence*, not a conclusion."""

    id: UUID
    method: AnomalyMethod
    feature_schema_version: str = Field(max_length=32)
    model_version: str | None = Field(default=None, max_length=64)
    score: float = Field(description="Raw model / statistic score (method-specific range).")
    normalized_score: float = Field(ge=0.0, le=1.0, description="Score mapped to [0,1].")
    threshold: float = Field(description="The threshold in force when this was scored.")
    is_anomaly: bool
    entity: EntityRef | None = None
    raw_event_id: UUID | None = None
    observed_at: datetime
    features: dict[str, float] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class ThreatScore(TenantScoped, TimestampedModel):
    """A deterministic composite score for one subject. `components` + `weights_version`
    make it fully reproducible."""

    id: UUID
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    score: float = Field(ge=0.0, le=1.0)
    components: dict[str, float] = Field(description="Named contributions before weighting.")
    weights_version: str = Field(max_length=32)
    scoring_status: ScoringStatus
    computed_at: datetime

    @field_validator("computed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class Detection(TenantScoped, TimestampedModel):
    """A finding. Every claim it makes is backed by an item in `evidence`."""

    id: UUID
    detector: DetectorKind
    rule_id: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    severity: Severity
    score: float = Field(ge=0.0, le=1.0)
    scoring_status: ScoringStatus
    status: DetectionStatus
    entities: list[EntityRef] = Field(default_factory=list, max_length=64)
    technique_ids: list[str] = Field(default_factory=list, max_length=32)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=128)
    raw_event_id: UUID | None = None
    dedup_key: str = Field(min_length=1, max_length=200)
    first_seen: datetime
    last_seen: datetime

    @field_validator("first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class SecurityAlert(TenantScoped, TimestampedModel):
    """Raised from a `Detection` that crosses the alerting threshold. The analyst-
    facing lifecycle object."""

    id: UUID
    detection_id: UUID
    severity: Severity
    status: AlertStatus
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    opened_at: datetime
    acknowledged_at: datetime | None = None
    closed_at: datetime | None = None

    @field_validator("opened_at", "acknowledged_at", "closed_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)
