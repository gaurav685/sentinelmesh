from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

_SIMILARITY = [
    {
        "kind": "threat_memory", "id": str(uuid.uuid4()), "score": 0.9,
        "technique_ids": ["T1110"], "last_seen": "2026-01-01T00:00:00Z", "exact_fallback": False,
    }
]
_PATTERN = {
    "id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "subject_type": "host",
    "subject_id": "web01", "pattern_kind": "technique_sequence", "technique_ids": ["T1110"],
    "occurrence_count": 1, "first_seen": "2026-01-01T00:00:00Z", "last_seen": "2026-01-01T00:00:00Z",
    "source": "attack_chain:c1", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
}
_FINGERPRINT = {
    "id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "subject_type": "identity",
    "subject_id": "svc-backup", "technique_ids": ["T1110"], "campaign_ids": ["c1"],
    "first_seen": "2026-01-01T00:00:00Z", "last_seen": "2026-01-01T00:00:00Z",
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
}
_CAMPAIGN = {
    "id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "status": "active",
    "chain_ids": ["c1"], "technique_ids": ["T1110"], "first_seen": "2026-01-01T00:00:00Z",
    "last_seen": "2026-01-01T00:00:00Z", "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}
_PREDICTION = {
    "kind": "attack_progression", "subject_type": "host", "subject_id": "web01",
    "prediction": "execution", "confidence": 0.5, "evidence": ["latest_stage=initial_access"],
    "features": {}, "model_version": "heuristic-v1", "generated_at": "2026-01-01T00:00:00Z",
}


def test_memory_endpoints_require_a_session(client: TestClient) -> None:
    assert client.post("/api/v1/soc/memory/similar", json={}).status_code == 401
    assert client.get("/api/v1/soc/memory/patterns").status_code == 401
    assert client.get("/api/v1/soc/memory/campaigns").status_code == 401
    assert client.post(
        "/api/v1/soc/predict/attack-progression", json={"chain_id": str(uuid.uuid4())}
    ).status_code == 401


def test_memory_endpoints_need_memory_read_permission(
    client: TestClient, fixture, do_login, csrf
) -> None:
    r = do_login("globex", fixture.globex_admin.email)  # no memory:read
    assert client.get("/api/v1/soc/memory/patterns", headers=csrf(r)).status_code == 403


def test_find_similar_proxies_to_memory_service(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.responses["mem_similar"] = _SIMILARITY
    r = client.post(
        "/api/v1/soc/memory/similar", json={"kind": "threat_memory", "technique_ids": ["T1110"]},
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 200
    assert r.json()[0]["score"] == 0.9
    assert ("mem_similar", fixture.acme.id) in ic.calls


def test_list_patterns(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["mem_patterns"] = [_PATTERN]
    r = client.get("/api/v1/soc/memory/patterns")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_get_fingerprint_404_when_none_recorded(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["mem_fingerprint"] = None
    r = client.get("/api/v1/soc/memory/fingerprints/identity/svc-backup")
    assert r.status_code == 404


def test_get_fingerprint_found(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["mem_fingerprint"] = _FINGERPRINT
    r = client.get("/api/v1/soc/memory/fingerprints/identity/svc-backup")
    assert r.status_code == 200
    assert r.json()["subject_id"] == "svc-backup"


def test_list_campaigns(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["mem_campaigns"] = [_CAMPAIGN]
    r = client.get("/api/v1/soc/memory/campaigns")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_get_campaign_404(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["mem_campaign"] = None
    r = client.get(f"/api/v1/soc/memory/campaigns/{uuid.uuid4()}")
    assert r.status_code == 404


def test_predict_attack_progression_proxies_and_keeps_the_disclaimer_fields(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.responses["predict_attack_progression"] = _PREDICTION
    r = client.post(
        "/api/v1/soc/predict/attack-progression", json={"chain_id": str(uuid.uuid4())},
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == 0.5
    assert body["model_version"] == "heuristic-v1"
    assert body["evidence"]


def test_predict_threat_trajectory_proxies(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.responses["predict_threat_trajectory"] = {**_PREDICTION, "subject_type": None, "kind": "threat_trajectory"}
    r = client.post(
        "/api/v1/soc/predict/threat-trajectory", json={"campaign_id": str(uuid.uuid4())},
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 200
    assert r.json()["subject_type"] is None
