from __future__ import annotations

import pytest

from sm_contracts import AttackStage
from sm_ml.predict import (
    predict_attack_progression,
    predict_lateral_movement,
    predict_next_action,
    predict_threat_trajectory,
)


def test_attack_progression_predicts_the_next_stage() -> None:
    out = predict_attack_progression(
        latest_stage=AttackStage.initial_access, distinct_stage_count=3,
        chain_score=0.5, chain_confidence=0.6,
    )
    assert out.prediction == AttackStage.execution.value
    assert 0.0 < out.confidence <= 1.0
    assert out.evidence


def test_attack_progression_at_final_stage_predicts_nothing() -> None:
    out = predict_attack_progression(
        latest_stage=AttackStage.impact, distinct_stage_count=10,
        chain_score=0.9, chain_confidence=0.7,
    )
    assert out.confidence == 0.0
    assert "final" in out.prediction


def test_attack_progression_unknown_stage_predicts_nothing() -> None:
    out = predict_attack_progression(
        latest_stage=AttackStage.unknown, distinct_stage_count=0,
        chain_score=0.0, chain_confidence=0.0,
    )
    assert out.confidence == 0.0
    assert "unknown" in out.prediction


def test_next_action_picks_an_unseen_historical_technique() -> None:
    out = predict_next_action(
        pattern_technique_ids=["T1110", "T1078", "T1059"], chain_technique_ids=["T1110"],
    )
    assert out.prediction in {"T1059", "T1078"}
    assert out.confidence > 0.0


def test_next_action_with_nothing_unseen_predicts_nothing() -> None:
    out = predict_next_action(pattern_technique_ids=["T1110"], chain_technique_ids=["T1110"])
    assert out.confidence == 0.0
    assert "none" in out.prediction


def test_lateral_movement_picks_the_most_similar_fingerprint() -> None:
    out = predict_lateral_movement(
        subject_technique_ids=["T1110", "T1078"],
        candidates=[
            ("host", "web02", ["T1110", "T1078"]),
            ("host", "db01", ["T1486", "T1490"]),
        ],
    )
    assert out.prediction == "host:web02"
    assert out.confidence > 0.0


def test_lateral_movement_with_no_candidates_predicts_nothing() -> None:
    out = predict_lateral_movement(subject_technique_ids=["T1110"], candidates=[])
    assert out.confidence == 0.0
    assert "none" in out.prediction


def test_lateral_movement_with_no_overlap_predicts_nothing() -> None:
    out = predict_lateral_movement(
        subject_technique_ids=["T1110"], candidates=[("host", "db01", ["T1486"])],
    )
    assert out.confidence == 0.0


@pytest.mark.parametrize(
    ("status", "chain_count", "expected"),
    [
        ("closed", 5, "concluded"),
        ("dormant", 2, "stalling"),
        ("active", 3, "escalating"),
        ("active", 1, "active"),
        ("active", 0, "unknown — no chains recorded yet"),
    ],
)
def test_threat_trajectory(status: str, chain_count: int, expected: str) -> None:
    out = predict_threat_trajectory(status=status, chain_count=chain_count)
    assert out.prediction == expected


def test_no_prediction_ever_claims_full_certainty() -> None:
    out = predict_threat_trajectory(status="closed", chain_count=5)
    assert out.confidence < 1.0
