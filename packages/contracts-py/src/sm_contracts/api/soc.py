"""SOC read-API contracts (Phase 9).

`api-gateway` is the browser-facing BFF: it reads the detection / alert / chain /
threat-score tables (tenant-scoped) and proxies the graph / threat-intel / MITRE
internal services. These are the response shapes the frontend's generated client
consumes — the frontend never re-declares them.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc
from ..enums import ScoringStatus, Severity, ThreatSubjectType

__all__ = [
    "MitreHeatmap",
    "MitreHeatmapCell",
    "RiskSubject",
    "SocSummary",
    "TimelineEntry",
    "TimelineResponse",
]


class RiskSubject(SmBaseModel):
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    score: float = Field(ge=0.0, le=1.0)
    scoring_status: ScoringStatus
    computed_at: datetime

    @field_validator("computed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class SocSummary(SmBaseModel):
    """The dashboard's top-of-page counters. Every number is a real row count for
    the caller's tenant — never a fabricated figure."""

    generated_at: datetime
    open_alerts: int = Field(ge=0)
    alerts_by_severity: dict[str, int] = Field(default_factory=dict)
    active_chains: int = Field(ge=0)
    detections_24h: int = Field(ge=0)
    top_risk_subjects: list[RiskSubject] = Field(default_factory=list, max_length=20)

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class MitreHeatmapCell(SmBaseModel):
    technique_id: str = Field(pattern=r"^T\d{4}(\.\d{3})?$")
    name: str = Field(default="", max_length=200)
    tactic_id: str | None = Field(default=None, pattern=r"^TA\d{4}$")
    subject_count: int = Field(ge=0)


class MitreHeatmap(SmBaseModel):
    matrix_version: str | None = None
    cells: list[MitreHeatmapCell] = Field(default_factory=list, max_length=1000)


class TimelineEntry(SmBaseModel):
    """One point on an entity's timeline — a detection, an alert transition, or a
    chain-stage advance. `kind` distinguishes them for the UI."""

    at: datetime
    kind: str = Field(min_length=1, max_length=32)
    severity: Severity | None = None
    title: str = Field(min_length=1, max_length=200)
    ref_id: str = Field(min_length=1, max_length=64)
    detail: dict[str, str] = Field(default_factory=dict)

    @field_validator("at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class TimelineResponse(SmBaseModel):
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    entries: list[TimelineEntry] = Field(default_factory=list, max_length=500)
