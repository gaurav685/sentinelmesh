from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sm_contracts import (
    CONFIDENCE_CEILING,
    EVENT_PAYLOAD_REGISTRY,
    N_KILL_CHAIN_STAGES,
    STAGE_ORDER,
    AttackChainPayload,
    AttackStage,
    ChainStatus,
    EventType,
    ThreatSubjectType,
    chain_dedup_key,
    chain_id_for,
    chain_window_start,
    stage_for_tactic,
    stage_for_technique,
    stages_for_techniques,
)

_NOW = datetime(2026, 9, 9, 14, 37, 5, tzinfo=UTC)


# ---- stage lookup: deterministic, never guessed -----------------------
@pytest.mark.parametrize(
    ("technique_id", "stage"),
    [
        ("T1110", AttackStage.credential_access),
        ("T1110.001", AttackStage.credential_access),   # sub-technique inherits parent's stage
        ("T1021", AttackStage.lateral_movement),
        ("T1048", AttackStage.exfiltration),
        ("T1059", AttackStage.execution),
        ("T1071.004", AttackStage.command_and_control),
        ("T9999", AttackStage.unknown),                 # unknown -> unknown, not a guess
        ("garbage", AttackStage.unknown),
    ],
)
def test_stage_for_technique(technique_id: str, stage: AttackStage) -> None:
    assert stage_for_technique(technique_id) is stage


def test_stage_for_tactic() -> None:
    assert stage_for_tactic("TA0008") is AttackStage.lateral_movement
    assert stage_for_tactic("ta0006") is AttackStage.credential_access
    assert stage_for_tactic("TA9999") is AttackStage.unknown


def test_stages_for_techniques_dedupes() -> None:
    assert stages_for_techniques(["T1110", "T1110.001", "T1021"]) == {
        AttackStage.credential_access,
        AttackStage.lateral_movement,
    }


def test_stage_order_covers_every_stage_and_unknown_sorts_first() -> None:
    assert set(STAGE_ORDER) == set(AttackStage)
    assert STAGE_ORDER[AttackStage.unknown] == -1
    reals = [s for s in AttackStage if s is not AttackStage.unknown]
    assert len(reals) == N_KILL_CHAIN_STAGES
    assert [STAGE_ORDER[s] for s in reals] == list(range(N_KILL_CHAIN_STAGES))


# ---- window / id determinism (out-of-order + at-least-once safe) ------
def test_chain_window_start_floors_to_the_window() -> None:
    start = chain_window_start(_NOW, 86_400)
    assert start == datetime(2026, 9, 9, 0, 0, 0, tzinfo=UTC)
    # a later event in the same day floors to the same start
    later = datetime(2026, 9, 9, 23, 59, 0, tzinfo=UTC)
    assert chain_window_start(later, 86_400) == start
    # the next day is a new window
    assert chain_window_start(datetime(2026, 9, 10, 0, 0, 1, tzinfo=UTC), 86_400) != start


def test_chain_id_is_deterministic_per_subject_and_window() -> None:
    key = chain_dedup_key(uuid.UUID(int=7), ThreatSubjectType.identity, "alice")
    w = chain_window_start(_NOW, 86_400)
    assert chain_id_for(key, w) == chain_id_for(key, w)
    # a different subject -> a different chain
    other = chain_dedup_key(uuid.UUID(int=7), ThreatSubjectType.identity, "bob")
    assert chain_id_for(other, w) != chain_id_for(key, w)


# ---- payload: registered + never claims certainty --------------------
def test_attack_chain_payload_round_trips_and_is_registered() -> None:
    p = AttackChainPayload(
        chain_id=uuid.uuid4(), tenant_id=uuid.uuid4(), subject_type=ThreatSubjectType.host,
        subject_id="web01", status=ChainStatus.active, first_seen=_NOW, last_seen=_NOW, updated_at=_NOW,
        stage_count=3, distinct_stage_count=3, latest_stage=AttackStage.exfiltration,
        progression=0.85, confidence=0.7, score=0.66, score_version="v1", scoring_status="ok",
        technique_ids=["T1110", "T1021", "T1048"], detection_count=5,
    )
    assert AttackChainPayload.model_validate_json(p.model_dump_json()) == p
    assert EVENT_PAYLOAD_REGISTRY[EventType.attack_chain_updated] is AttackChainPayload


def test_chain_confidence_cannot_reach_certainty() -> None:
    with pytest.raises(ValidationError):
        AttackChainPayload(
            chain_id=uuid.uuid4(), tenant_id=uuid.uuid4(), subject_type=ThreatSubjectType.host,
            subject_id="web01", status=ChainStatus.active, first_seen=_NOW, last_seen=_NOW, updated_at=_NOW,
            stage_count=3, distinct_stage_count=3, latest_stage=AttackStage.impact,
            progression=1.0, confidence=CONFIDENCE_CEILING + 0.01, score=0.9,
            score_version="v1", scoring_status="ok", detection_count=9,
        )
