"""End-to-end flow: analyst login → run a synthetic scenario → verify the
simulation badge → logout.

Drives the real api-gateway `TestClient` through the simulation pipeline:
login → POST /api/v1/soc/simulation/run → the BFF proxies to
`simulation-service` → the result carries the `synthetic` badge (always True
for a drill, never real activity) → logout.

Constitution §5: every step asserts on a real, observed response.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import SecurityFixture

_RUN_REQUEST = {
    "name": "drill", "kind": "brute_force", "seed": 1,
    "target_host": "sim-host-00", "target_identity": "sim-id-alice", "intensity": 2,
}
_SCENARIO_RESULT = {
    "scenario_id": "scn-1", "kind": "brute_force", "seed": 1,
    "target_host": "sim-host-00", "target_identity": "sim-id-alice", "intensity": 2,
    "event_count": 0, "events": [],
}


@pytest.mark.e2e
def test_simulation_flow_login_run_scenario_verify_badge_logout(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
    sec_csrf: Callable[[Any], dict[str, str]],
) -> None:
    """Full simulation session: authenticate, run a synthetic drill, verify
    the `synthetic` badge on the result (a drill is never real activity), then
    log out and confirm the session is dead."""
    sec_fixture.services.internal_client.responses["sim_run_scenario"] = _SCENARIO_RESULT

    # ---- step 1: login ------------------------------------------------
    login = sec_client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "acme",
            "email": sec_fixture.acme_analyst.email,
            "password": "TestP@ss1!",
        },
    )
    assert login.status_code == 200
    csrf_headers = sec_csrf(login)

    # ---- step 2: run a synthetic scenario ------------------------------
    run = sec_client.post(
        "/api/v1/soc/simulation/run",
        json=_RUN_REQUEST,
        headers=csrf_headers,
    )
    assert run.status_code == 200
    body = run.json()
    assert body["scenario_id"] == "scn-1"
    assert body["seed"] == 1

    # ---- step 3: verify the simulation badge ---------------------------
    # `synthetic` is the drill badge — always True for a scenario run, and
    # it is what separates a synthetic drill from real telemetry downstream.
    assert body["synthetic"] is True
    assert ("sim_run_scenario", sec_fixture.acme.id) in sec_fixture.services.internal_client.calls

    # ---- step 4: logout invalidates the session immediately ------------
    logout = sec_client.post("/api/v1/auth/logout", headers=csrf_headers)
    assert logout.status_code == 200
    assert sec_client.get("/api/v1/me").status_code == 401