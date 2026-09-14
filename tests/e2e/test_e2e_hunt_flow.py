"""End-to-end flow: analyst login → submit natural-language hunt → get plan → logout.

Drives the real api-gateway `TestClient` through the threat-hunting pipeline:
login → POST /api/v1/soc/hunt with a natural-language `query` → the BFF asks
`ai-analyst` for a `QueryPlan` → `graph-service` executes it → the result is
returned with a grounded explanation → logout.

Constitution §5: every step asserts on a real, observed response.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import SecurityFixture

_PLAN = {
    "intent": "list_related",
    "selectors": [{"type": "host", "value": "web01"}],
    "rel_types": [],
    "limits": {"max_depth": 2, "max_rows": 100},
}
_HUNT_RESULT = {
    "intent": "list_related",
    "plan": _PLAN,
    "rows": [{"id": "n1", "labels": ["IpAddress"], "properties": {"ip": "10.0.0.9"}}],
    "row_count": 1,
    "truncated": False,
    "cypher_fingerprint": "fp1",
    "explanation": "",
}


@pytest.mark.e2e
def test_hunt_flow_login_submit_nl_hunt_get_plan_logout(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
    sec_csrf: Callable[[Any], dict[str, str]],
) -> None:
    """Full hunt session: authenticate, submit a natural-language hunt, walk
    the planner → executor → explainer pipeline, verify the history row, then
    log out and confirm the session is dead."""
    ic = sec_fixture.services.internal_client
    ic.responses["hunt_plan"] = {"supported": True, "plan": _PLAN, "unsupported_reason": ""}
    ic.responses["graph_hunt"] = _HUNT_RESULT
    ic.responses["hunt_explain"] = {**_HUNT_RESULT, "explanation": "one related ip [rows]"}

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

    # ---- step 2: submit a natural-language hunt ------------------------
    hunt = sec_client.post(
        "/api/v1/soc/hunt",
        json={"query": "what talks to web01"},
        headers=csrf_headers,
    )
    assert hunt.status_code == 200
    body = hunt.json()
    assert body["supported"] is True
    assert body["result"]["row_count"] == 1
    assert body["result"]["explanation"] == "one related ip [rows]"

    # the planner and the executor were both called, scoped to the session tenant
    assert ("hunt_plan", sec_fixture.acme.id) in ic.calls
    assert ("graph_hunt", sec_fixture.acme.id) in ic.calls

    # the hunt history row records the NL query and the mode
    hunts = sec_fixture.services.soc_repository.hunts
    assert hunts, "the hunt must have been recorded in SOC history"
    assert hunts[-1]["mode"] == "nl"
    assert hunts[-1]["nl_query"] == "what talks to web01"
    assert hunts[-1]["supported"] is True

    # ---- step 3: logout invalidates the session immediately ------------
    logout = sec_client.post("/api/v1/auth/logout", headers=csrf_headers)
    assert logout.status_code == 200
    assert sec_client.get("/api/v1/me").status_code == 401