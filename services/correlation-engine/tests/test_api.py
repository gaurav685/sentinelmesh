from __future__ import annotations

import uuid
from typing import Any

from .conftest import TENANT_ID, _chain_model, token


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def test_chains_requires_a_valid_service_token(client: Any) -> None:
    assert client.get("/api/v1/chains").status_code == 401
    assert client.get("/api/v1/chains", headers=_auth(token(audience="graph-service"))).status_code == 401
    assert client.get("/api/v1/chains", headers=_auth("garbage")).status_code == 401


def test_list_and_get_are_scoped_to_the_token_tenant(client: Any) -> None:
    mine = _chain_model(tenant_id=TENANT_ID)
    theirs = _chain_model(tenant_id=uuid.uuid4())
    client.fake_repo.store[str(mine.id)] = mine
    client.fake_repo.store[str(theirs.id)] = theirs

    listed = client.get("/api/v1/chains", headers=_auth(token())).json()
    assert listed["count"] == 1
    assert listed["chains"][0]["id"] == str(mine.id)

    got = client.get(f"/api/v1/chains/{mine.id}", headers=_auth(token()))
    assert got.status_code == 200
    assert got.json()["subject_id"] == "alice"

    # another tenant's chain is a 404, not a leak
    assert client.get(f"/api/v1/chains/{theirs.id}", headers=_auth(token())).status_code == 404


def test_get_unknown_chain_is_404(client: Any) -> None:
    assert client.get(f"/api/v1/chains/{uuid.uuid4()}", headers=_auth(token())).status_code == 404


def test_healthz_is_open(client: Any) -> None:
    assert client.get("/healthz").status_code == 200


def test_health_deps_reports_every_dependency(client: Any) -> None:
    r = client.get("/health/deps")
    assert r.status_code == 200
    assert {d["name"] for d in r.json()["dependencies"]} == {
        "postgres", "kafka_consumer", "kafka_producer",
    }
