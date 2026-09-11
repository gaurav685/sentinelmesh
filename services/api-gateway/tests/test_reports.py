from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

_REPORT = {
    "id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z", "kind": "incident", "status": "complete",
    "subject_type": "host", "subject_id": "web01", "title": "Host incident",
    "requested_by": str(uuid.uuid4()), "generated_at": "2026-01-01T00:00:00Z",
    "incident_metadata": {}, "timeline": [], "affected_assets": [], "detection_ids": [],
    "evidence": [], "chain_ids": [], "technique_ids": [], "threat_score": None,
    "findings": [], "recommendations": [], "confidence": None, "provenance": [],
    "missing_sections": [], "storage_key": None,
}
_REPORT_DOWNLOAD = {"report": _REPORT, "download_url": "https://minio.example/x.pdf?sig=abc"}
_NARRATIVE = {
    "id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z", "chain_id": str(uuid.uuid4()), "subject_type": "host",
    "subject_id": "web01", "beats": [], "summary": "A walkthrough.", "cited_refs": [],
    "confidence": "low", "model": {}, "degraded": True, "degraded_reason": "llm_disabled",
    "simulated": False, "generated_at": "2026-01-01T00:00:00Z",
}


def test_reports_endpoints_require_a_session(client: TestClient) -> None:
    assert client.post("/api/v1/soc/reports", json={}).status_code == 401
    assert client.get(f"/api/v1/soc/reports/{uuid.uuid4()}").status_code == 401
    assert client.get(f"/api/v1/soc/incidents/{uuid.uuid4()}/narrative").status_code == 401


def test_create_report_proxies_to_reporting_service(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.responses["create_report"] = _REPORT
    r = client.post(
        "/api/v1/soc/reports",
        json={"kind": "incident", "subject_type": "host", "subject_id": "web01", "title": "t"},
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "complete"
    assert ("create_report", fixture.acme.id) in ic.calls


def test_create_report_never_trusts_requested_by_from_the_body(
    client: TestClient, fixture, do_login, csrf
) -> None:
    """`CreateReportRequest` has no `requested_by` field -- the browser
    cannot supply one; a client that tries gets a 422 (`extra="forbid"`),
    not a silently-accepted override of the authenticated principal."""
    r = client.post(
        "/api/v1/soc/reports",
        json={
            "kind": "incident", "subject_type": "host", "subject_id": "web01", "title": "t",
            "requested_by": str(uuid.uuid4()),
        },
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 422


def test_compliance_report_requires_the_tenant_admin_or_lead_role(
    client: TestClient, fixture, do_login, csrf
) -> None:
    # acme_analyst has reports:generate but role "analyst", not tenant_admin/lead.
    r = client.post(
        "/api/v1/soc/reports",
        json={"kind": "compliance", "subject_type": "host", "subject_id": "web01", "title": "t"},
        headers=csrf(do_login("acme", fixture.acme_analyst.email)),
    )
    assert r.status_code == 403


def test_compliance_report_allowed_for_tenant_admin(
    client: TestClient, fixture, do_login, csrf
) -> None:
    ic = fixture.services.internal_client
    ic.responses["create_report"] = {**_REPORT, "kind": "compliance"}
    r = client.post(
        "/api/v1/soc/reports",
        json={"kind": "compliance", "subject_type": "host", "subject_id": "web01", "title": "t"},
        headers=csrf(do_login("acme", fixture.acme_admin.email)),
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "compliance"


def test_get_report_404_when_not_found(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["get_report"] = None
    r = client.get(f"/api/v1/soc/reports/{uuid.uuid4()}")
    assert r.status_code == 404


def test_get_report_returns_the_download_url(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["get_report"] = _REPORT_DOWNLOAD
    r = client.get(f"/api/v1/soc/reports/{uuid.uuid4()}")
    assert r.status_code == 200
    assert r.json()["download_url"].startswith("https://minio.example/")


def test_get_narrative_needs_detections_read_permission(
    client: TestClient, fixture, do_login, csrf
) -> None:
    r = do_login("globex", fixture.globex_admin.email)
    resp = client.get(f"/api/v1/soc/incidents/{uuid.uuid4()}/narrative", headers=csrf(r))
    assert resp.status_code == 403


def test_get_narrative_404_when_the_chain_is_not_found(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["get_narrative"] = None
    r = client.get(f"/api/v1/soc/incidents/{uuid.uuid4()}/narrative")
    assert r.status_code == 404


def test_get_narrative_proxies_to_ai_analyst(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_analyst.email)
    fixture.services.internal_client.responses["get_narrative"] = _NARRATIVE
    r = client.get(f"/api/v1/soc/incidents/{uuid.uuid4()}/narrative")
    assert r.status_code == 200
    assert r.json()["summary"] == "A walkthrough."
