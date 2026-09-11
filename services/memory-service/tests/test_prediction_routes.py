from __future__ import annotations

import uuid
from typing import Any

from .conftest import campaign, fingerprint, full_chain, pattern, token

_BASE = "/api/v1/predict"


def test_no_bearer_token_is_unauthenticated(client: Any) -> None:
    resp = client.post(f"{_BASE}/attack-progression", json={"chain_id": str(uuid.uuid4())})
    assert resp.status_code == 401


def test_attack_progression_predicts_the_next_stage(client: Any, chains: Any) -> None:
    tenant_id = uuid.uuid4()
    chain = full_chain(
        tenant_id, stages=[], distinct_stage_count=2, confidence=0.6, score=0.5,
    )
    chains.chain_response = chain
    headers = {"authorization": f"Bearer {token(tenant=tenant_id)}"}
    resp = client.post(f"{_BASE}/attack-progression", json={"chain_id": str(chain.id)}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "attack_progression"
    assert body["model_version"] == "heuristic-v1"
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["evidence"]


def test_attack_progression_404_when_chain_missing(client: Any, chains: Any) -> None:
    chains.chain_response = None
    resp = client.post(
        f"{_BASE}/attack-progression", json={"chain_id": str(uuid.uuid4())},
        headers={"authorization": f"Bearer {token()}"},
    )
    assert resp.status_code == 404


def test_next_action_uses_the_subjects_pattern_history(client: Any, chains: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    chain = full_chain(tenant_id, technique_ids=["T1110"])
    chains.chain_response = chain
    repo.patterns_response = [pattern(tenant_id, technique_ids=["T1110", "T1078"])]
    headers = {"authorization": f"Bearer {token(tenant=tenant_id)}"}
    resp = client.post(f"{_BASE}/next-action", json={"chain_id": str(chain.id)}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["prediction"] == "T1078"


def test_lateral_movement_404_with_no_fingerprint(client: Any, repo: Any) -> None:
    repo.fingerprint_response = None
    resp = client.post(
        f"{_BASE}/lateral-movement", json={"subject_type": "identity", "subject_id": "svc-backup"},
        headers={"authorization": f"Bearer {token()}"},
    )
    assert resp.status_code == 404


def test_lateral_movement_picks_the_most_similar_other_subject(client: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    repo.fingerprint_response = fingerprint(tenant_id, technique_ids=["T1110"])
    repo.fingerprints_response = [
        fingerprint(tenant_id, subject_id="web02", technique_ids=["T1110"]),
    ]
    headers = {"authorization": f"Bearer {token(tenant=tenant_id)}"}
    resp = client.post(
        f"{_BASE}/lateral-movement", json={"subject_type": "identity", "subject_id": "svc-backup"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["prediction"] == "identity:web02"


def test_threat_trajectory_404_when_campaign_missing(client: Any, repo: Any) -> None:
    repo.campaign_response = None
    resp = client.post(
        f"{_BASE}/threat-trajectory", json={"campaign_id": str(uuid.uuid4())},
        headers={"authorization": f"Bearer {token()}"},
    )
    assert resp.status_code == 404


def test_threat_trajectory_escalating_for_a_growing_active_campaign(client: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    repo.campaign_response = campaign(
        tenant_id, status="active", chain_ids=["c1", "c2", "c3"],
    )
    headers = {"authorization": f"Bearer {token(tenant=tenant_id)}"}
    resp = client.post(
        f"{_BASE}/threat-trajectory", json={"campaign_id": str(uuid.uuid4())}, headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["prediction"] == "escalating"
    assert body["subject_type"] is None
