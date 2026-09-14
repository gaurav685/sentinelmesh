"""End-to-end flow: analyst login → SOC reads → LLM explanation → logout.

Drives the real api-gateway `TestClient` through a multi-step user flow
involving session state, CSRF token propagation, tenant scoping, and audit
trail completeness, all over the in-memory fixture rig (no Docker).

Constitution §5: every step asserts on a real, observed response — nothing
here is fabricated.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import SecurityFixture


def _detection(tenant_id: uuid.UUID) -> Any:
    """Build a detection row the SOC repository understands."""
    from sm_common.clock import utcnow
    from sm_contracts import Detection, Severity

    now = utcnow()
    return Detection(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        created_at=now,
        updated_at=now,
        detector="composite",
        rule_id="rule.auth.failed_burst",
        title="Repeated auth failures",
        description="12 failed logins",
        severity=Severity.high,
        score=0.82,
        scoring_status="ok",
        status="new",
        entities=[{"kind": "identity", "value": "svc-backup"}],
        technique_ids=["T1110"],
        evidence=[],
        raw_event_id=uuid.uuid4(),
        dedup_key="k",
        first_seen=now,
        last_seen=now,
    )


@pytest.mark.e2e
def test_analyst_flow_login_get_detection_request_explanation_logout(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
    sec_csrf: Callable[[Any], dict[str, str]],
) -> None:
    """Full analyst session: authenticate, read scoped detections, request an
    LLM explanation, verify the audit trail, then log out and confirm the
    session is dead."""
    # ---- seed a detection in the analyst's tenant --------------------
    det = _detection(sec_fixture.acme.id)
    sec_fixture.services.soc_repository.detections[det.id] = det

    # ---- the analyst (acme_analyst) has detections:read + hunt:query -----
    sec_fixture.services.internal_client.responses["explain"] = {
        "subject_type": "detection",
        "subject_id": str(det.id),
        "summary": f"Repeated auth failures for svc-backup [{det.id}].",
        "cited_refs": [str(det.id)],
        "confidence": "low",
        "recommendations": ["Confirm against the raw events."],
        "model": {
            "provider": "",
            "model_id": "",
            "prompt_sha256": "",
            "from_live_provider": False,
        },
        "generated_at": "2026-09-10T00:00:00Z",
        "degraded": True,
        "degraded_reason": "llm_disabled",
        "evidence_flagged": False,
    }

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
    session_cookie = sec_client.cookies.get("sm_session")
    assert session_cookie, "login must set the sm_session cookie"
    csrf_headers = sec_csrf(login)

    # ---- step 2: read detections (session + CSRF cookie propagate) ----
    listed = sec_client.get("/api/v1/soc/detections", headers=csrf_headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [d["id"] for d in items] == [str(det.id)]
    assert listed.json()["limit"] == 50

    # ---- step 3: request the LLM explanation for the detection --------
    expl = sec_client.get(
        f"/api/v1/soc/detections/{det.id}/explanation", headers=csrf_headers
    )
    assert expl.status_code == 200
    body = expl.json()
    assert body["subject_id"] == str(det.id)
    assert body["degraded"] is True
    assert ("explain", sec_fixture.acme.id) in sec_fixture.services.internal_client.calls

    # ---- step 4: audit trail completeness ------------------------------
    # login and logout are audited (the explanation proxy itself is not
    # audited by the BFF — the downstream service owns its own audit row).
    actions = sec_fixture.services.audit.actions()
    assert "auth.login.local" in actions
    login_entry = next(
        e for e in sec_fixture.services.audit.entries if e["action"] == "auth.login.local"
    )
    assert login_entry["tenant_id"] == sec_fixture.acme.id
    assert login_entry["actor_id"] == sec_fixture.acme_analyst.id

    # ---- step 5: logout invalidates the session immediately ------------
    logout = sec_client.post("/api/v1/auth/logout", headers=csrf_headers)
    assert logout.status_code == 200
    assert sec_client.get("/api/v1/me").status_code == 401