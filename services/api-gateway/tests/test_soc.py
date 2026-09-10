from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from sm_common.clock import utcnow
from sm_contracts import Detection, MitreHeatmapCell, SecurityAlert, Severity


def _detection(tenant_id: uuid.UUID, *, severity: Severity = Severity.high) -> Detection:
    now = utcnow()
    return Detection(
        id=uuid.uuid4(), tenant_id=tenant_id, created_at=now, updated_at=now,
        detector="composite", rule_id="rule.auth.failed_burst", title="Repeated auth failures",
        description="12 failed logins", severity=severity, score=0.82, scoring_status="ok",
        status="new", entities=[{"kind": "identity", "value": "svc-backup"}],
        technique_ids=["T1110"], evidence=[], raw_event_id=uuid.uuid4(), dedup_key="k",
        first_seen=now, last_seen=now,
    )


def _alert(tenant_id: uuid.UUID) -> SecurityAlert:
    now = utcnow()
    return SecurityAlert(
        id=uuid.uuid4(), tenant_id=tenant_id, created_at=now, updated_at=now,
        detection_id=uuid.uuid4(), severity=Severity.critical, status="open",
        title="Critical: brute force", summary="", opened_at=now,
    )


# ---- authn / authz ---------------------------------------------
def test_soc_endpoints_require_a_session(client: TestClient) -> None:
    for path in ("/api/v1/soc/summary", "/api/v1/soc/detections", "/api/v1/soc/alerts",
                 "/api/v1/soc/mitre/heatmap", "/api/v1/soc/chains"):
        assert client.get(path).status_code == 401, path


def test_soc_read_denied_without_the_permission(client: TestClient, fixture, do_login) -> None:
    # globex_admin has tenant_admin perms but NOT detections:read
    do_login("globex", fixture.globex_admin.email)
    r = client.get("/api/v1/soc/detections")
    assert r.status_code == 403


# ---- detections / alerts, tenant-scoped ----------------------
def test_detections_are_scoped_to_the_session_tenant(client: TestClient, fixture, do_login) -> None:
    repo = fixture.services.soc_repository
    mine = _detection(fixture.acme.id)
    theirs = _detection(fixture.globex.id)
    repo.detections[mine.id] = mine
    repo.detections[theirs.id] = theirs

    do_login("acme", fixture.acme_analyst.email)
    body = client.get("/api/v1/soc/detections").json()
    assert [d["id"] for d in body["items"]] == [str(mine.id)]
    assert body["limit"] == 50

    got = client.get(f"/api/v1/soc/detections/{mine.id}")
    assert got.status_code == 200 and got.json()["title"] == "Repeated auth failures"
    # a detection in another tenant is a 404, not a leak
    assert client.get(f"/api/v1/soc/detections/{theirs.id}").status_code == 404


def test_alerts_list_and_detail(client: TestClient, fixture, do_login) -> None:
    repo = fixture.services.soc_repository
    a = _alert(fixture.acme.id)
    repo.alerts[a.id] = a
    do_login("acme", fixture.acme_analyst.email)
    listed = client.get("/api/v1/soc/alerts").json()
    assert listed["items"][0]["severity"] == "critical"
    assert client.get(f"/api/v1/soc/alerts/{a.id}").status_code == 200
    assert client.get(f"/api/v1/soc/alerts/{uuid.uuid4()}").status_code == 404


def test_summary_returns_real_counts(client: TestClient, fixture, do_login) -> None:
    repo = fixture.services.soc_repository
    repo.detections[uuid.uuid4()] = _detection(fixture.acme.id)
    repo.alerts[uuid.uuid4()] = _alert(fixture.acme.id)
    do_login("acme", fixture.acme_analyst.email)
    body = client.get("/api/v1/soc/summary").json()
    assert body["detections_24h"] == 1
    assert body["open_alerts"] == 1


def test_mitre_heatmap_merges_local_counts_with_the_remote_matrix_version(
    client: TestClient, fixture, do_login
) -> None:
    fixture.services.soc_repository.heatmap_cells = [
        MitreHeatmapCell(technique_id="T1110", tactic_id="TA0006", subject_count=3)
    ]
    fixture.services.internal_client.responses["mitre_heatmap"] = {"matrix_version": "14.1"}
    do_login("acme", fixture.acme_analyst.email)
    body = client.get("/api/v1/soc/mitre/heatmap").json()
    assert body["matrix_version"] == "14.1"
    assert body["cells"][0]["subject_count"] == 3


# ---- proxied endpoints -------------------------------------
def test_chains_proxies_correlation_engine_with_the_session_tenant(
    client: TestClient, fixture, do_login
) -> None:
    fixture.services.internal_client.responses["chains"] = {"count": 0, "chains": []}
    do_login("acme", fixture.acme_analyst.email)
    r = client.get("/api/v1/soc/chains")
    assert r.status_code == 200 and r.json() == {"count": 0, "chains": []}
    name, tenant_id = fixture.services.internal_client.calls[-1]
    assert name == "chains" and tenant_id == fixture.acme.id


def test_a_dependency_outage_is_503_not_500(client: TestClient, fixture, do_login) -> None:
    fixture.services.internal_client.fail = True
    do_login("acme", fixture.acme_analyst.email)
    assert client.get("/api/v1/soc/chains").status_code == 503
    assert client.get(
        "/api/v1/soc/graph/neighbors", params={"label": ":Host", "key": "web01"}
    ).status_code == 503


def test_graph_endpoints_need_hunt_query(client: TestClient, fixture, do_login) -> None:
    do_login("globex", fixture.globex_admin.email)  # has neither detections:read nor hunt:query
    assert client.get(
        "/api/v1/soc/graph/neighbors", params={"label": ":Host", "key": "web01"}
    ).status_code == 403


def test_chain_detail_404_when_the_service_returns_none(client: TestClient, fixture, do_login) -> None:
    fixture.services.internal_client.responses["chain"] = None
    do_login("acme", fixture.acme_analyst.email)
    assert client.get(f"/api/v1/soc/chains/{uuid.uuid4()}").status_code == 404


def test_graph_neighbors_returns_a_typed_neighbourhood(client: TestClient, fixture, do_login) -> None:
    fixture.services.internal_client.responses["graph_neighbors"] = {
        "depth": 2,
        "nodes": [{"id": "h-1", "labels": ["Host"], "properties": {"name": "web01"}}],
        "edges": [{"src": "h-1", "dst": "h-1", "type": "SELF", "properties": {}}],
        "truncated": True,
    }
    do_login("acme", fixture.acme_analyst.email)
    r = client.get(
        "/api/v1/soc/graph/neighbors", params={"label": "Host", "key": "web01", "depth": 2}
    )
    assert r.status_code == 200
    body = r.json()
    # graph-service did not send a root_id; the BFF fills it from the requested key
    assert body["root_id"] == "web01"
    assert body["truncated"] is True
    assert body["depth"] == 2
    assert body["nodes"][0]["id"] == "h-1"


def test_graph_neighbors_503_when_the_service_answers_with_a_non_object(
    client: TestClient, fixture, do_login
) -> None:
    fixture.services.internal_client.responses["graph_neighbors"] = ["not", "an", "object"]
    do_login("acme", fixture.acme_analyst.email)
    r = client.get("/api/v1/soc/graph/neighbors", params={"label": "Host", "key": "web01"})
    assert r.status_code == 503


def test_detection_explanation_gathers_evidence_and_proxies_the_analyst(
    client: TestClient, fixture, do_login
) -> None:
    det = _detection(fixture.acme.id)
    fixture.services.soc_repository.detections[det.id] = det
    fixture.services.internal_client.responses["explain"] = {
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
    do_login("acme", fixture.acme_analyst.email)
    r = client.get(f"/api/v1/soc/detections/{det.id}/explanation")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert body["subject_id"] == str(det.id)
    assert ("explain", fixture.acme.id) in fixture.services.internal_client.calls


def test_detection_explanation_404_for_an_unknown_detection(
    client: TestClient, fixture, do_login
) -> None:
    do_login("acme", fixture.acme_analyst.email)
    assert client.get(f"/api/v1/soc/detections/{uuid.uuid4()}/explanation").status_code == 404


def test_detection_explanation_503_when_the_analyst_is_down(
    client: TestClient, fixture, do_login
) -> None:
    det = _detection(fixture.acme.id)
    fixture.services.soc_repository.detections[det.id] = det
    fixture.services.internal_client.fail = True
    do_login("acme", fixture.acme_analyst.email)
    assert client.get(f"/api/v1/soc/detections/{det.id}/explanation").status_code == 503
