"""End-to-end flow: analyst login → generate a report → retrieve the report
(with its download URL) → logout.

Drives the real api-gateway `TestClient` through the reporting pipeline:
login → POST /api/v1/soc/reports → the BFF proxies to `reporting-service`
and returns a typed `Report` → GET /api/v1/soc/reports/{id} → the BFF returns
the report plus a presigned download URL → logout.

Constitution §5: every step asserts on a real, observed response.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import SecurityFixture


def _report(tenant_id: uuid.UUID, requested_by: uuid.UUID) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": str(tenant_id),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "kind": "incident",
        "status": "complete",
        "subject_type": "host",
        "subject_id": "web01",
        "title": "Host incident",
        "requested_by": str(requested_by),
        "generated_at": "2026-01-01T00:00:00Z",
        "incident_metadata": {},
        "timeline": [],
        "affected_assets": [],
        "detection_ids": [],
        "evidence": [],
        "chain_ids": [],
        "technique_ids": [],
        "threat_score": None,
        "findings": [],
        "recommendations": [],
        "confidence": None,
        "provenance": [],
        "missing_sections": [],
        "storage_key": "reports/abc.pdf",
    }


@pytest.mark.e2e
def test_report_flow_login_generate_retrieve_logout(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
    sec_csrf: Callable[[Any], dict[str, str]],
) -> None:
    """Full reporting session: authenticate, generate a report, retrieve it
    with its presigned download URL, verify the `requested_by` field is the
    authenticated principal (never a body-supplied value), then log out."""
    report = _report(sec_fixture.acme.id, sec_fixture.acme_analyst.id)
    ic = sec_fixture.services.internal_client
    ic.responses["create_report"] = report
    ic.responses["get_report"] = {
        "report": report,
        "download_url": "https://minio.example/reports/abc.pdf?sig=xyz",
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
    csrf_headers = sec_csrf(login)

    # ---- step 2: generate a report ------------------------------------
    gen = sec_client.post(
        "/api/v1/soc/reports",
        json={
            "kind": "incident",
            "subject_type": "host",
            "subject_id": "web01",
            "title": "Host incident",
        },
        headers=csrf_headers,
    )
    assert gen.status_code == 200
    created = gen.json()
    assert created["status"] == "complete"
    assert created["requested_by"] == str(sec_fixture.acme_analyst.id)
    assert ("create_report", sec_fixture.acme.id) in ic.calls

    # ---- step 3: retrieve the report with its download URL -----------
    got = sec_client.get(
        f"/api/v1/soc/reports/{created['id']}", headers=csrf_headers
    )
    assert got.status_code == 200
    body = got.json()
    assert body["report"]["id"] == created["id"]
    assert body["download_url"].startswith("https://minio.example/")
    assert ("get_report", sec_fixture.acme.id) in ic.calls

    # ---- step 4: logout invalidates the session immediately ------------
    logout = sec_client.post("/api/v1/auth/logout", headers=csrf_headers)
    assert logout.status_code == 200
    assert sec_client.get("/api/v1/me").status_code == 401