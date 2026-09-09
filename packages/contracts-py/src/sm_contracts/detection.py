"""Detection + anomaly contracts (Phase 5; docs/CONTRACTS.md §6, ADR-013).

The detection pipeline is:

    telemetry -> features -> anomaly score -> evidence -> detection -> alert

`detection-engine` is the system of record (Postgres `detection` / `anomaly` /
`threat_score` / `security_alert`). It publishes a thin `DetectionPayload` on the
`detections` topic for the read-model projection and downstream consumers — the
full body stays in Postgres, the payload carries enough to render a SOC list row
and to fan out a notification.

Non-fabrication (Constitution §3): a `Detection` states only what its `evidence`
supports. No model accuracy, F1, ROC-AUC or latency number appears in any
contract — those require a real training/evaluation run (ADR-024).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from .common import SmBaseModel, to_utc
from .enums import DetectorKind, ScoringStatus, Severity
from .events import EVENT_PAYLOAD_REGISTRY, EventType
from .telemetry import EntityRef

__all__ = [
    "DETECTION_PAYLOADS",
    "DetectionPayload",
    "EvidenceItem",
    "EvidenceKind",
    "detection_dedup_key",
    "detection_id_for",
]

_DETECTION_NS = uuid.UUID("6f9d4c21-8a3b-5e7f-9c1d-2b4a6e8f0d3c")


class EvidenceKind(StrEnum):
    """What a single piece of detection evidence is."""

    event = "event"                 # a canonical telemetry event (`raw_event_id`)
    feature = "feature"             # an extracted feature value + its schema
    rule_match = "rule_match"       # a rule fired; `ref` is the rule id
    anomaly_score = "anomaly_score" # a model / statistical score vs. its threshold
    threshold = "threshold"        # the adaptive threshold in force + how it was derived
    graph_path = "graph_path"       # a path returned by graph-service
    ti_indicator = "ti_indicator"   # a threat-intel match (Phase 6)
    technique = "technique"         # a MITRE ATT&CK technique mapping (Phase 6)


class EvidenceItem(SmBaseModel):
    """One grounded fact behind a detection. `provenance` is `<service>:<id>` so a
    reader can chase every claim back to its source."""

    kind: EvidenceKind
    ref: str = Field(min_length=1, max_length=256, description="Id / key of the evidence subject.")
    summary: str = Field(min_length=1, max_length=512)
    detail: dict[str, Any] = Field(default_factory=dict)
    provenance: str = Field(min_length=1, max_length=128, description="'<service>:<id>'.")


class DetectionPayload(SmBaseModel):
    """`detections` topic event — the thin projection of a Postgres `detection`."""

    detection_id: UUID
    tenant_id: UUID
    occurred_at: datetime = Field(description="Event time of the telemetry that triggered this. UTC.")
    detected_at: datetime = Field(description="When detection-engine raised it. UTC.")
    detector: DetectorKind
    rule_id: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    severity: Severity
    score: float = Field(ge=0.0, le=1.0, description="Composite threat score in [0,1].")
    scoring_status: ScoringStatus
    raw_event_id: UUID | None = Field(default=None, description="Lineage to the canonical event.")
    entities: list[EntityRef] = Field(default_factory=list, max_length=64)
    technique_ids: list[str] = Field(default_factory=list, max_length=32)
    evidence_count: int = Field(ge=0)
    dedup_key: str = Field(min_length=1, max_length=200)

    @field_validator("occurred_at", "detected_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


def detection_dedup_key(tenant_id: UUID, detector: str, rule_id: str | None, subject: str) -> str:
    """Stable key for suppressing a repeat of the *same* finding about the *same*
    subject. `subject` is the primary entity value (or the raw event id for a
    one-shot rule)."""
    return f"{tenant_id}|{detector}|{rule_id or '-'}|{subject}"


def detection_id_for(dedup_key: str, window: str) -> UUID:
    """Deterministic detection id: same finding + same time bucket -> same id, so
    an at-least-once reprocess updates the row instead of duplicating it.
    `window` is a coarse bucket the caller chooses (e.g. an ISO date or hour)."""
    return uuid.uuid5(_DETECTION_NS, f"{dedup_key}|{window}")


DETECTION_PAYLOADS: dict[EventType, type[SmBaseModel]] = {
    EventType.detection_raised: DetectionPayload,
}

EVENT_PAYLOAD_REGISTRY.update(DETECTION_PAYLOADS)
