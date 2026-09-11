"""Threat-report contracts (Phase 14; reqs 22, 33).

`services/reporting-service` assembles a `Report` by calling out to
detection-engine, graph-service, mitre-service, ai-analyst, and
memory-service for content, renders it (PDF, ADR-019 object storage), and
produces a thin `report.generated` projection — mirroring `chains.py`'s
`AttackChainPayload` / `memory.py`'s `CampaignUpdatePayload`.

Non-fabrication (Constitution §3): every narrative statement in a report (a
finding, a recommendation, a timeline point) carries a `GroundingKind` tag so
a reader can tell ACTUAL SYSTEM EVIDENCE apart from INFERENCE, PREDICTION,
and SYNTHETIC DEMO DATA. A report is never assembled from invented
incidents; a missing content dependency lands the section in
`missing_sections` and the report as a whole as `partial`, never faked.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from .common import SmBaseModel, TenantScoped, TimestampedModel, to_utc
from .enums import Severity, ThreatSubjectType
from .events import EVENT_PAYLOAD_REGISTRY, EventType

__all__ = [
    "REPORT_PAYLOADS",
    "GroundedStatement",
    "GroundingKind",
    "Report",
    "ReportAsset",
    "ReportDownload",
    "ReportGeneratedPayload",
    "ReportKind",
    "ReportStatus",
    "ReportTimelineEntry",
]


class GroundingKind(StrEnum):
    """How a statement in a report is backed. Every `GroundedStatement` and
    `ReportTimelineEntry` carries one — never left implicit (Constitution
    §3).

    - `evidence`: a real detection/chain/telemetry record the platform
      itself produced; `ref` points at it.
    - `inference`: a deterministic derivation from evidence (e.g. a stage
      rollup), not a new observation.
    - `prediction`: `sm_ml.predict` output — a forecast, never fact
      (mirrors `Prediction`, Phase 13).
    - `synthetic`: from `simulation-service` (Phase 12) demo/scenario data —
      never real, always labeled as such.
    """

    evidence = "evidence"
    inference = "inference"
    prediction = "prediction"
    synthetic = "synthetic"


#: A closed, additive set — a new report kind is a new literal value, never
#: free text (Constitution §10).
ReportKind = Literal["incident", "executive_summary", "soc", "compliance"]
ReportStatus = Literal["pending", "partial", "complete", "failed"]


class GroundedStatement(SmBaseModel):
    """One finding, recommendation, or analyst statement. `tier` says which
    of the four grounding kinds it is; `ref` traces it back to its source
    (a detection id, a chain id, a prediction id...) whenever `tier` is not
    `synthetic`."""

    text: str = Field(min_length=1, max_length=4000)
    tier: GroundingKind
    ref: str | None = Field(default=None, max_length=256)


class ReportTimelineEntry(SmBaseModel):
    """Timeline point inside a report. Deliberately a separate type from
    `TimelineEntry` (`api/soc.py`) even though the shape is close — a
    report's timeline is a persisted, immutable snapshot at generation
    time, not a live query result, and additionally carries `tier`."""

    at: datetime
    kind: str = Field(min_length=1, max_length=32)
    severity: Severity | None = None
    title: str = Field(min_length=1, max_length=200)
    ref_id: str = Field(min_length=1, max_length=64)
    tier: GroundingKind = GroundingKind.evidence

    @field_validator("at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class ReportAsset(SmBaseModel):
    """One affected asset referenced by a report."""

    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    role: str = Field(min_length=1, max_length=64, description='e.g. "victim", "source".')


class Report(TenantScoped, TimestampedModel):
    """A generated report. The rendered artifact (PDF) lives in object
    storage at `storage_key`; this row is the durable record of what was
    generated, from what, and how sure the platform is about each part of
    it. `status` is `partial` (never faked) whenever a content dependency
    could not be reached — see `missing_sections`."""

    id: UUID
    kind: ReportKind
    status: ReportStatus
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=200)
    requested_by: UUID
    generated_at: datetime | None = None

    incident_metadata: dict[str, str] = Field(default_factory=dict)
    timeline: list[ReportTimelineEntry] = Field(default_factory=list, max_length=500)
    affected_assets: list[ReportAsset] = Field(default_factory=list, max_length=200)
    detection_ids: list[str] = Field(default_factory=list, max_length=500)
    evidence: list[GroundedStatement] = Field(default_factory=list, max_length=500)
    chain_ids: list[str] = Field(default_factory=list, max_length=100)
    technique_ids: list[str] = Field(default_factory=list, max_length=200)
    threat_score: float | None = Field(default=None, ge=0.0, le=1.0)
    findings: list[GroundedStatement] = Field(default_factory=list, max_length=200)
    recommendations: list[GroundedStatement] = Field(default_factory=list, max_length=200)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    #: Which upstream services actually contributed content — the report's
    #: own provenance, distinct from any one statement's `GroundingKind`.
    provenance: list[str] = Field(default_factory=list, max_length=20)
    #: Populated whenever `status == "partial"`: which of the sections
    #: above could not be filled in because a content dependency was
    #: unreachable.
    missing_sections: list[str] = Field(default_factory=list, max_length=20)
    storage_key: str | None = Field(default=None, max_length=512)

    @field_validator("generated_at")
    @classmethod
    def _utc_opt(cls, v: datetime | None) -> datetime | None:
        return to_utc(v) if v is not None else None


class ReportGeneratedPayload(SmBaseModel):
    """`report.generated` topic event (`EventType.report_generated`). Thin
    projection — enough to fan a notification out; the full report (and its
    rendered artifact) stay in Postgres / object storage."""

    report_id: UUID
    tenant_id: UUID
    kind: ReportKind
    status: ReportStatus
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class ReportDownload(SmBaseModel):
    """`GET /api/v1/reports/{id}` response — the report plus a fresh,
    time-limited presigned download URL (ADR-019: never a public bucket,
    never a raw path a caller could manipulate)."""

    report: Report
    download_url: str | None = Field(
        default=None, description="Presigned; None until the report is `complete` or `partial`."
    )


REPORT_PAYLOADS: dict[EventType, type[SmBaseModel]] = {
    EventType.report_generated: ReportGeneratedPayload,
}

EVENT_PAYLOAD_REGISTRY.update(REPORT_PAYLOADS)
