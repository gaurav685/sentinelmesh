from __future__ import annotations

from sm_correlation_engine.staging import resolve_subject, stage_detection

from sm_contracts import AttackStage, EntityRef, ScoringStatus, Severity, ThreatSubjectType

from .conftest import detection_payload


def test_detection_takes_the_furthest_stage_its_techniques_imply() -> None:
    # credential_access (7) + lateral_movement (9) -> lateral_movement is furthest
    staged = stage_detection(detection_payload(technique_ids=["T1110", "T1021"]))
    assert staged.stage is AttackStage.lateral_movement
    assert staged.stage_order == 9


def test_detection_with_no_mappable_technique_is_unknown() -> None:
    staged = stage_detection(detection_payload(technique_ids=["T9999"], rule_id="rule.custom"))
    assert staged.stage is AttackStage.unknown
    assert staged.stage_order == -1
    assert staged.ti_corroborated is False


def test_ti_rule_marks_the_detection_ti_corroborated() -> None:
    staged = stage_detection(
        detection_payload(technique_ids=[], rule_id="rule.ti.known_bad_indicator")
    )
    assert staged.ti_corroborated is True
    assert staged.stage is AttackStage.unknown  # a TI hit is not itself a technique


def test_staged_detection_carries_severity_and_score() -> None:
    staged = stage_detection(
        detection_payload(severity=Severity.high, score=0.82, scoring_status=ScoringStatus.degraded)
    )
    assert staged.severity is Severity.high
    assert staged.detection_score == 0.82
    assert staged.scoring_status is ScoringStatus.degraded


def test_resolve_subject_prefers_the_explicit_subject() -> None:
    p = detection_payload(subject=(ThreatSubjectType.host, "web01"))
    assert resolve_subject(p) == (ThreatSubjectType.host, "web01")


def test_resolve_subject_falls_back_to_the_first_entity() -> None:
    p = detection_payload(subject=None)
    p = p.model_copy(update={"entities": [EntityRef(kind="ip", value="10.0.0.9")]})
    assert resolve_subject(p) == (ThreatSubjectType.ip, "10.0.0.9")


def test_resolve_subject_falls_back_to_a_host_placeholder() -> None:
    p = detection_payload(subject=None).model_copy(update={"entities": []})
    assert resolve_subject(p) == (ThreatSubjectType.host, "unknown")
