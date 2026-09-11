from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

_RUN_REQUEST = {
    "name": "drill", "kind": "brute_force", "seed": 1,
    "target_host": "sim-host-00", "target_identity": "sim-id-alice", "intensity": 2,
}
_SCENARIO_RESULT = {
    "scenario_id": "scn-1", "kind": "brute_force", "seed": 1,
    "target_host": "sim-host-00", "target_identity": "sim-id-alice", "intensity": 2,
    "event_count": 0, "events": [],
}
_TWIN_SNAPSHOT = {"seed": 1, "assets": [], "relations": [], "weaknesses": []}
_BLAST_RESULT = {"seed": 1, "seeds": ["sim-host-00"], "reached": ["sim-host-00"], "score": 0.2}
_DECOY = {
    "id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "name": "ssh-honeypot",
    "kind": "honeypot_host", "network_boundary": "isolated", "status": "active",
    "ttl_seconds": 3600, "created_at": "2026-01-01T00:00:00Z",
}
_INTERACTION = {
    "id": str(uuid.uuid4()), "decoy_id": _DECOY["id"], "tenant_id": _DECOY["tenant_id"],
    "source": "10.0.0.9", "captured_at": "2026-01-01T00:00:00Z",
}


def test_simulation_endpoints_require_a_session(client: TestClient) -> None:
    assert client.post("/api/v1/soc/simulation/run", json=_RUN_REQUEST).status_code == 401
    assert client.get("/api/v1/soc/simulation/twin").status_code == 401
    assert client.post(
        "/api/v1/soc/simulation/blast-radius", json={"seed": 1, "seeds": ["sim-host-00"]}
    ).status_code == 401
    assert client.post(
        "/api/v1/soc/deception/decoys",
        json={"name": "x", "kind": "honeypot_host", "network_boundary": "isolated"},
    ).status_code == 401
    assert client.get("/api/v1/soc/deception/decoys").status_code == 401


def test_run_scenario_needs_simulation_run_permission(
    client: TestClient, fixture, do_login, csrf
) -> None:
    r = do_login("globex", fixture.globex_admin.email)  # no simulation:run
    assert client.post(
        "/api/v1/soc/simulation/run", json=_RUN_REQUEST, headers=csrf(r)
    ).status_code == 403


def test_run_scenario_proxies_to_simulation_service(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.responses["sim_run_scenario"] = _SCENARIO_RESULT
    r = client.post(
        "/api/v1/soc/simulation/run", json=_RUN_REQUEST,
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 200
    assert r.json()["scenario_id"] == "scn-1"
    assert ("sim_run_scenario", fixture.acme.id) in ic.calls


def test_run_scenario_isolation_refusal_is_422_not_503(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.validation_errors["sim_run_scenario"] = "target_host is not a synthetic id"
    r = client.post(
        "/api/v1/soc/simulation/run", json=_RUN_REQUEST,
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 422


def test_get_twin_snapshot(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["sim_twin"] = _TWIN_SNAPSHOT
    r = client.get("/api/v1/soc/simulation/twin", params={"seed": 1})
    assert r.status_code == 200
    assert r.json()["seed"] == 1


def test_blast_radius_proxies_to_simulation_service(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.responses["sim_blast_radius"] = _BLAST_RESULT
    r = client.post(
        "/api/v1/soc/simulation/blast-radius",
        json={"seed": 1, "seeds": ["sim-host-00"]},
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 200
    assert r.json()["reached"] == ["sim-host-00"]


def test_deception_endpoints_need_deception_manage_permission(
    client: TestClient, fixture, do_login, csrf
) -> None:
    r = do_login("globex", fixture.globex_admin.email)  # no deception:manage
    assert client.post(
        "/api/v1/soc/deception/decoys",
        json={"name": "x", "kind": "honeypot_host", "network_boundary": "isolated"},
        headers=csrf(r),
    ).status_code == 403


def test_register_list_get_decoy(client: TestClient, fixture, do_login, csrf) -> None:
    ic = fixture.services.internal_client
    ic.responses["register_decoy"] = _DECOY
    ic.responses["list_decoys"] = [_DECOY]
    ic.responses["get_decoy"] = _DECOY
    headers = csrf(do_login("acme", fixture.acme_analyst.email))

    reg = client.post(
        "/api/v1/soc/deception/decoys",
        json={"name": "ssh-honeypot", "kind": "honeypot_host", "network_boundary": "isolated"},
        headers=headers,
    )
    assert reg.status_code == 200
    assert reg.json()["id"] == _DECOY["id"]

    listed = client.get("/api/v1/soc/deception/decoys")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == _DECOY["id"]

    got = client.get(f"/api/v1/soc/deception/decoys/{_DECOY['id']}")
    assert got.status_code == 200


def test_get_decoy_404_when_the_service_returns_none(
    client: TestClient, fixture, do_login
) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["get_decoy"] = None
    r = client.get(f"/api/v1/soc/deception/decoys/{uuid.uuid4()}")
    assert r.status_code == 404


def test_teardown_decoy(client: TestClient, fixture, do_login, csrf) -> None:
    ic = fixture.services.internal_client
    torn = {**_DECOY, "status": "torn_down", "torn_down_at": "2026-01-01T00:05:00Z"}
    ic.responses["teardown_decoy"] = torn
    r = client.delete(
        f"/api/v1/soc/deception/decoys/{_DECOY['id']}",
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "torn_down"


def test_list_decoy_interactions(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["list_decoy_interactions"] = [_INTERACTION]
    r = client.get(f"/api/v1/soc/deception/decoys/{_DECOY['id']}/interactions")
    assert r.status_code == 200
    assert r.json()[0]["source"] == "10.0.0.9"


def test_list_decoy_interactions_404_when_the_decoy_is_missing(
    client: TestClient, fixture, do_login
) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["list_decoy_interactions"] = None
    r = client.get(f"/api/v1/soc/deception/decoys/{uuid.uuid4()}/interactions")
    assert r.status_code == 404
