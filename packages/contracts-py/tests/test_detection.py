from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sm_contracts import (
    EVENT_PAYLOAD_REGISTRY,
    Anomaly,
    Detection,
    DetectionPayload,
    EventType,
    EvidenceItem,
    EvidenceKind,
    SecurityAlert,
    ThreatScore,
    detection_dedup_key,
    detection_id_for,
)
from sm_contracts.enums import (
    AlertStatus,
    AnomalyMethod,
    DetectionStatus,
    DetectorKind,
    ScoringStatus,
    Severity,
    ThreatSubjectType,
)
from sm_contracts.telemetry import EntityRef

_NOW = datetime.now(UTC)
_T = uuid.uuid4()


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.rule_match, ref="rule.auth.bruteforce",
        summary="12 failed logins in 5 minutes", provenance="detection-engine:abc",
    )


def test_detection_payload_round_trips() -> None:
    p = DetectionPayload(
        detection_id=uuid.uuid4(), tenant_id=_T, occurred_at=_NOW, detected_at=_NOW,
        detector=DetectorKind.rule, rule_id="rule.auth.bruteforce",
        title="Brute-force against web01", severity=Severity.high, score=0.82,
        scoring_status=ScoringStatus.ok, raw_event_id=uuid.uuid4(),
        entities=[EntityRef(kind="identity", value="alice")], technique_ids=["T1110"],
        evidence_count=3, dedup_key="k",
    )
    assert DetectionPayload.model_validate_json(p.model_dump_json()) == p


def test_score_must_be_in_unit_interval() -> None:
    with pytest.raises(ValidationError):
        DetectionPayload(
            detection_id=uuid.uuid4(), tenant_id=_T, occurred_at=_NOW, detected_at=_NOW,
            detector=DetectorKind.statistical, title="x", severity=Severity.low,
            score=1.4, scoring_status=ScoringStatus.ok, evidence_count=0, dedup_key="k",
        )


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DetectionPayload(
            detection_id=uuid.uuid4(), tenant_id=_T, occurred_at=datetime(2026, 1, 1),  # noqa: DTZ001
            detected_at=_NOW, detector=DetectorKind.rule, title="x", severity=Severity.low,
            score=0.1, scoring_status=ScoringStatus.ok, evidence_count=0, dedup_key="k",
        )


def test_evidence_item_requires_provenance() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(kind=EvidenceKind.event, ref="e1", summary="s", provenance="")


def test_dedup_key_is_stable_and_tenant_scoped() -> None:
    a = detection_dedup_key(_T, "rule", "r1", "alice")
    assert a == detection_dedup_key(_T, "rule", "r1", "alice")
    assert a != detection_dedup_key(uuid.uuid4(), "rule", "r1", "alice")
    assert detection_dedup_key(_T, "rule", None, "alice") != a


def test_detection_id_is_deterministic_per_window() -> None:
    k = detection_dedup_key(_T, "rule", "r1", "alice")
    assert detection_id_for(k, "2026-09-09") == detection_id_for(k, "2026-09-09")
    assert detection_id_for(k, "2026-09-09") != detection_id_for(k, "2026-09-10")


def test_registered_for_detection_raised() -> None:
    assert EVENT_PAYLOAD_REGISTRY[EventType.detection_raised] is DetectionPayload


def test_detection_dto_carries_evidence() -> None:
    d = Detection(
        id=uuid.uuid4(), tenant_id=_T, created_at=_NOW, updated_at=_NOW,
        detector=DetectorKind.composite, title="t", severity=Severity.medium, score=0.5,
        scoring_status=ScoringStatus.degraded, status=DetectionStatus.new,
        evidence=[_evidence()], dedup_key="k", first_seen=_NOW, last_seen=_NOW,
    )
    assert d.evidence[0].kind is EvidenceKind.rule_match
    assert d.scoring_status is ScoringStatus.degraded


def test_anomaly_normalized_score_bounds() -> None:
    with pytest.raises(ValidationError):
        Anomaly(
            id=uuid.uuid4(), tenant_id=_T, created_at=_NOW, updated_at=_NOW,
            method=AnomalyMethod.mad_zscore, feature_schema_version="1",
            score=9.9, normalized_score=1.2, threshold=3.0, is_anomaly=True, observed_at=_NOW,
        )


def test_threat_score_and_alert_dtos() -> None:
    ts = ThreatScore(
        id=uuid.uuid4(), tenant_id=_T, created_at=_NOW, updated_at=_NOW,
        subject_type=ThreatSubjectType.identity, subject_id="alice", score=0.7,
        components={"rule": 0.9, "anomaly": 0.5}, weights_version="v1",
        scoring_status=ScoringStatus.ok, computed_at=_NOW,
    )
    assert ts.components["rule"] == 0.9
    alert = SecurityAlert(
        id=uuid.uuid4(), tenant_id=_T, created_at=_NOW, updated_at=_NOW,
        detection_id=uuid.uuid4(), severity=Severity.critical, status=AlertStatus.open,
        title="t", opened_at=_NOW - timedelta(minutes=1),
    )
    assert alert.acknowledged_at is None
