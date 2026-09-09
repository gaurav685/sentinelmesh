"""Place one detection on a kill-chain stage.

A detection carries the candidate ATT&CK technique ids its rule named. Its stage
is the **furthest** non-`unknown` stage those techniques imply — a detection's
position in the kill chain is its most advanced implication. A detection with no
mappable technique lands on `AttackStage.unknown`; it is never forced onto a
stage (Constitution §3).

Threat-intel corroboration is read from the rule id: `detection-engine` raises
`rule.ti.known_bad_indicator` (the `rule.ti.*` family) when an entity on the
event matches a threat-intel indicator. That rule carries no technique, so a
TI-only detection is stage `unknown` but still marks the chain as
TI-corroborated for scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sm_contracts import (
    STAGE_ORDER,
    AttackStage,
    DetectionPayload,
    ScoringStatus,
    Severity,
    ThreatSubjectType,
    stages_for_techniques,
)

__all__ = ["StagedDetection", "resolve_subject", "stage_detection"]

_TI_RULE_PREFIX = "rule.ti."


@dataclass(frozen=True)
class StagedDetection:
    detection_id: str
    stage: AttackStage
    stage_order: int
    technique_ids: tuple[str, ...]
    severity: Severity
    detection_score: float
    scoring_status: ScoringStatus
    occurred_at: datetime
    ti_corroborated: bool


def stage_detection(payload: DetectionPayload) -> StagedDetection:
    techniques = tuple(dict.fromkeys(payload.technique_ids))
    real = stages_for_techniques(list(techniques)) - {AttackStage.unknown}
    stage = max(real, key=lambda s: STAGE_ORDER[s]) if real else AttackStage.unknown
    return StagedDetection(
        detection_id=str(payload.detection_id),
        stage=stage,
        stage_order=STAGE_ORDER[stage],
        technique_ids=techniques,
        severity=payload.severity,
        detection_score=payload.score,
        scoring_status=payload.scoring_status,
        occurred_at=payload.occurred_at,
        ti_corroborated=bool(payload.rule_id and payload.rule_id.startswith(_TI_RULE_PREFIX)),
    )


def resolve_subject(payload: DetectionPayload) -> tuple[ThreatSubjectType, str]:
    """The subject a chain groups on: the detection's explicit subject, else its
    first entity, else a host placeholder."""
    if payload.subject_type is not None and payload.subject_id:
        return payload.subject_type, payload.subject_id
    if payload.entities:
        first = payload.entities[0]
        mapping = {
            "identity": ThreatSubjectType.identity,
            "host": ThreatSubjectType.host,
            "ip": ThreatSubjectType.ip,
            "domain": ThreatSubjectType.domain,
        }
        return mapping.get(first.kind.value, ThreatSubjectType.host), first.value
    return ThreatSubjectType.host, "unknown"
