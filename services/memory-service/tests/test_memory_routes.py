from __future__ import annotations

import uuid
from typing import Any

from .conftest import campaign, fingerprint, pattern, token

_BASE = "/api/v1/memory"


def test_no_bearer_token_is_unauthenticated(client: Any) -> None:
    body = {"kind": "threat_memory", "technique_ids": ["T1110"]}
    assert client.post(f"{_BASE}/similar", json=body).status_code == 401
    assert client.get(f"{_BASE}/patterns").status_code == 401
    assert client.get(f"{_BASE}/campaigns").status_code == 401


def test_find_similar_returns_matches(client: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    from sm_contracts import SimilarityMatch

    repo.similar_response = [
        SimilarityMatch(
            kind="threat_memory", id=uuid.uuid4(), score=0.9, technique_ids=["T1110"],
            last_seen=pattern(tenant_id).last_seen, exact_fallback=False,
        )
    ]
    headers = {"authorization": f"Bearer {token(tenant=tenant_id)}"}
    resp = client.post(
        f"{_BASE}/similar", json={"kind": "threat_memory", "technique_ids": ["T1110"]}, headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["score"] == 0.9
    assert "feature_vector" not in body[0]


def test_find_similar_rejects_an_empty_technique_list(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.post(f"{_BASE}/similar", json={"kind": "threat_memory", "technique_ids": []}, headers=headers)
    assert resp.status_code == 422


def test_list_patterns(client: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    repo.patterns_response = [pattern(tenant_id)]
    resp = client.get(f"{_BASE}/patterns", headers={"authorization": f"Bearer {token(tenant=tenant_id)}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_fingerprint_404_when_none_recorded(client: Any, repo: Any) -> None:
    repo.fingerprint_response = None
    resp = client.get(
        f"{_BASE}/fingerprints/identity/svc-backup", headers={"authorization": f"Bearer {token()}"}
    )
    assert resp.status_code == 404


def test_get_fingerprint_found(client: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    repo.fingerprint_response = fingerprint(tenant_id)
    resp = client.get(
        f"{_BASE}/fingerprints/identity/svc-backup", headers={"authorization": f"Bearer {token(tenant=tenant_id)}"}
    )
    assert resp.status_code == 200
    assert resp.json()["subject_id"] == "svc-backup"


def test_list_campaigns(client: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    repo.campaigns_response = [campaign(tenant_id)]
    resp = client.get(f"{_BASE}/campaigns", headers={"authorization": f"Bearer {token(tenant=tenant_id)}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_campaign_404(client: Any, repo: Any) -> None:
    repo.campaign_response = None
    resp = client.get(
        f"{_BASE}/campaigns/{uuid.uuid4()}", headers={"authorization": f"Bearer {token()}"}
    )
    assert resp.status_code == 404


def test_get_campaign_found(client: Any, repo: Any) -> None:
    tenant_id = uuid.uuid4()
    c = campaign(tenant_id)
    repo.campaign_response = c
    resp = client.get(
        f"{_BASE}/campaigns/{c.id}", headers={"authorization": f"Bearer {token(tenant=tenant_id)}"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(c.id)
