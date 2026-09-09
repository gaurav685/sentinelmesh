"""Attack-chain contracts (Phase 7; req 6).

The correlation layer turns a stream of independent detections into multi-stage
*attack chains*:

    detections -> attack stages -> attack chain -> chain threat score

A chain groups the detections about one subject (an identity / host / ip) inside
one time window, places each detection on an ATT&CK-derived kill-chain **stage**,
and records how far the activity has progressed.

Non-fabrication (Constitution §3):

- A chain **never asserts certainty**. `confidence` and `progression` are bounded
  in `[0, CONFIDENCE_CEILING]` / `[0, 1]` and are explicitly probabilistic.
- Stage assignment is a deterministic lookup, not a guess. A technique the
  platform does not have a mapping for lands on `AttackStage.unknown` — it is
  never forced onto a stage.
- Every stage keeps the ids of the detections that put it there; nothing about a
  chain is stated without a detection behind it.

`AttackChainPayload` is the thin `attack_chains` topic projection; the full body
(per-stage evidence) stays in Postgres (`attack_chain` / `attack_chain_stage`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from .common import SmBaseModel, TenantScoped, TimestampedModel, to_utc
from .enums import ScoringStatus, Severity, ThreatSubjectType
from .events import EVENT_PAYLOAD_REGISTRY, EventType

__all__ = [
    "CHAIN_PAYLOADS",
    "CONFIDENCE_CEILING",
    "N_KILL_CHAIN_STAGES",
    "STAGE_ORDER",
    "TACTIC_STAGE",
    "TECHNIQUE_STAGE",
    "AttackChainModel",
    "AttackChainPayload",
    "AttackStage",
    "ChainStageModel",
    "ChainStatus",
    "chain_dedup_key",
    "chain_id_for",
    "chain_window_start",
    "stage_for_tactic",
    "stage_for_technique",
    "stages_for_techniques",
]

_CHAIN_NS = uuid.UUID("2c1a7e64-9b0d-5f38-a4c2-7e6d1b9f03a5")

# A chain's confidence is never 1.0 — the evidence is always probabilistic.
CONFIDENCE_CEILING = 0.95


class AttackStage(StrEnum):
    """Kill-chain stage, one per enterprise ATT&CK tactic, in kill-chain order.

    `unknown` is a real, first-class value: a detection whose techniques the
    platform cannot place goes here rather than being forced onto a stage.
    """

    reconnaissance = "reconnaissance"
    resource_development = "resource_development"
    initial_access = "initial_access"
    execution = "execution"
    persistence = "persistence"
    privilege_escalation = "privilege_escalation"
    defense_evasion = "defense_evasion"
    credential_access = "credential_access"
    discovery = "discovery"
    lateral_movement = "lateral_movement"
    collection = "collection"
    command_and_control = "command_and_control"
    exfiltration = "exfiltration"
    impact = "impact"
    unknown = "unknown"


# Kill-chain position. `unknown` sorts first (-1) so it never inflates progression.
STAGE_ORDER: dict[AttackStage, int] = {
    AttackStage.unknown: -1,
    AttackStage.reconnaissance: 0,
    AttackStage.resource_development: 1,
    AttackStage.initial_access: 2,
    AttackStage.execution: 3,
    AttackStage.persistence: 4,
    AttackStage.privilege_escalation: 5,
    AttackStage.defense_evasion: 6,
    AttackStage.credential_access: 7,
    AttackStage.discovery: 8,
    AttackStage.lateral_movement: 9,
    AttackStage.collection: 10,
    AttackStage.command_and_control: 11,
    AttackStage.exfiltration: 12,
    AttackStage.impact: 13,
}

N_KILL_CHAIN_STAGES = 14
"""Number of real (non-`unknown`) stages — the denominator for `progression`."""

# ATT&CK enterprise tactic id -> stage. This is the full enterprise tactic set;
# it does not change with a catalog import (tactic ids are stable in ATT&CK).
TACTIC_STAGE: dict[str, AttackStage] = {
    "TA0043": AttackStage.reconnaissance,
    "TA0042": AttackStage.resource_development,
    "TA0001": AttackStage.initial_access,
    "TA0002": AttackStage.execution,
    "TA0003": AttackStage.persistence,
    "TA0004": AttackStage.privilege_escalation,
    "TA0005": AttackStage.defense_evasion,
    "TA0006": AttackStage.credential_access,
    "TA0007": AttackStage.discovery,
    "TA0008": AttackStage.lateral_movement,
    "TA0009": AttackStage.collection,
    "TA0011": AttackStage.command_and_control,
    "TA0010": AttackStage.exfiltration,
    "TA0040": AttackStage.impact,
}

# Technique -> stage for the techniques SentinelMesh's own detection rules emit.
# Each choice is the *earliest* kill-chain tactic ATT&CK lists for that technique,
# so a chain's progression is not overstated. This map is deliberately small and
# auditable; a technique not here resolves to `AttackStage.unknown`. It is NOT a
# claim of ATT&CK coverage — `mitre-service` remains the source for the catalog.
TECHNIQUE_STAGE: dict[str, AttackStage] = {
    "T1110": AttackStage.credential_access,       # Brute Force
    "T1078": AttackStage.initial_access,          # Valid Accounts (earliest of 4 tactics)
    "T1550": AttackStage.defense_evasion,         # Use Alternate Authentication Material
    "T1021": AttackStage.lateral_movement,        # Remote Services
    "T1048": AttackStage.exfiltration,            # Exfiltration Over Alternative Protocol
    "T1059": AttackStage.execution,               # Command and Scripting Interpreter
    "T1071": AttackStage.command_and_control,     # Application Layer Protocol
    "T1568": AttackStage.command_and_control,     # Dynamic Resolution
}


def stage_for_tactic(tactic_id: str) -> AttackStage:
    """ATT&CK tactic id -> `AttackStage`; an unrecognised id -> `unknown`."""
    return TACTIC_STAGE.get(tactic_id.upper(), AttackStage.unknown)


def stage_for_technique(technique_id: str) -> AttackStage:
    """ATT&CK technique id (`T1110` or `T1110.001`) -> `AttackStage`.

    A sub-technique inherits its parent's stage. A technique with no known
    mapping -> `AttackStage.unknown` (never guessed).
    """
    base = technique_id.split(".", 1)[0].upper()
    return TECHNIQUE_STAGE.get(base, AttackStage.unknown)


def stages_for_techniques(technique_ids: list[str]) -> set[AttackStage]:
    return {stage_for_technique(t) for t in technique_ids}


class ChainStatus(StrEnum):
    """Lifecycle of a chain's *evidence* — not an analyst verdict.

    A chain is never automatically `confirmed`; confirmation is a human action on
    the alert/investigation layer (Constitution §17), not something the
    correlator asserts.
    """

    forming = "forming"    # a single stage so far
    active = "active"      # >= 2 stages and evidence still arriving
    dormant = "dormant"    # no new evidence within the dormancy window


class ChainStageModel(SmBaseModel):
    """One kill-chain stage within a chain, with the detections behind it."""

    stage: AttackStage
    stage_order: int = Field(ge=-1, le=13)
    detection_ids: list[UUID] = Field(default_factory=list, max_length=2000)
    technique_ids: list[str] = Field(default_factory=list, max_length=64)
    max_severity: Severity
    max_detection_score: float = Field(ge=0.0, le=1.0)
    detection_count: int = Field(ge=0)
    first_seen: datetime
    last_seen: datetime

    @field_validator("first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class AttackChainModel(TenantScoped, TimestampedModel):
    """The full chain as returned by `correlation-engine`'s read API."""

    id: UUID
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    status: ChainStatus
    window_start: datetime
    first_seen: datetime
    last_seen: datetime
    stages: list[ChainStageModel] = Field(default_factory=list, max_length=15)
    distinct_stage_count: int = Field(ge=0, le=15)
    progression: float = Field(ge=0.0, le=1.0, description="Furthest kill-chain position reached, normalised.")
    confidence: float = Field(
        ge=0.0, le=CONFIDENCE_CEILING,
        description="Probabilistic estimate that this is a coordinated chain. Never 1.0.",
    )
    score: float = Field(ge=0.0, le=1.0, description="Deterministic chain threat score.")
    score_version: str = Field(min_length=1, max_length=32)
    scoring_status: ScoringStatus
    ti_corroborated: bool = Field(
        default=False, description="At least one member detection matched a threat-intel indicator."
    )
    technique_ids: list[str] = Field(default_factory=list, max_length=128)
    detection_count: int = Field(ge=0)
    notes: list[str] = Field(
        default_factory=list, max_length=32,
        description="Machine-readable caveats, e.g. 'out_of_order_observed', 'conflicting_severity'.",
    )

    @field_validator("window_start", "first_seen", "last_seen")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class AttackChainPayload(SmBaseModel):
    """`attack_chains` topic event (`EventType.attack_chain_updated`).

    Thin projection: enough to render a chain row and to fan a notification out.
    The per-stage evidence stays in Postgres.
    """

    chain_id: UUID
    tenant_id: UUID
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    status: ChainStatus
    first_seen: datetime
    last_seen: datetime
    updated_at: datetime
    stage_count: int = Field(ge=0, description="Total stage rows (includes 'unknown').")
    distinct_stage_count: int = Field(ge=0, description="Distinct real kill-chain stages.")
    latest_stage: AttackStage
    progression: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=CONFIDENCE_CEILING)
    score: float = Field(ge=0.0, le=1.0)
    score_version: str = Field(min_length=1, max_length=32)
    scoring_status: ScoringStatus
    ti_corroborated: bool = False
    technique_ids: list[str] = Field(default_factory=list, max_length=128)
    detection_count: int = Field(ge=0)

    @field_validator("first_seen", "last_seen", "updated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


def chain_dedup_key(tenant_id: UUID, subject_type: ThreatSubjectType, subject_id: str) -> str:
    """A chain's identity within a window: one chain per (tenant, subject)."""
    return f"{tenant_id}|{subject_type.value}|{subject_id}"


def chain_window_start(occurred_at: datetime, window_seconds: int) -> datetime:
    """Floor `occurred_at` to the start of its tumbling window.

    A fixed tumbling window (not a sliding one) keeps chain ids deterministic
    under at-least-once redelivery and out-of-order events: the same detection
    always lands in the same window and therefore the same chain.
    """
    epoch = int(occurred_at.timestamp())
    floored = epoch - (epoch % window_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)


def chain_id_for(dedup_key: str, window_start: datetime) -> UUID:
    """Deterministic chain id: same subject + same window -> same id, so an
    at-least-once reprocess upserts the chain instead of duplicating it."""
    return uuid.uuid5(_CHAIN_NS, f"{dedup_key}|{window_start.isoformat()}")


CHAIN_PAYLOADS: dict[EventType, type[SmBaseModel]] = {
    EventType.attack_chain_updated: AttackChainPayload,
}

EVENT_PAYLOAD_REGISTRY.update(CHAIN_PAYLOADS)
