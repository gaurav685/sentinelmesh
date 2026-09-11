from __future__ import annotations

import uuid
from typing import Any

from .conftest import token

_BASE = "/api/v1/reports"


def test_create_report_requires_a_bearer_token(client: Any) -> None:
    body = {
        "kind": "incident", "subject_type": "host", "subject_id": "web01",
        "title": "t", "requested_by": str(uuid.uuid4()),
    }
    assert client.post(_BASE, json=body).status_code == 401


def test_create_report_generates_and_returns_a_report(client: Any) -> None:
    body = {
        "kind": "incident", "subject_type": "host", "subject_id": "web01",
        "title": "Host incident", "requested_by": str(uuid.uuid4()),
    }
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.post(_BASE, json=body, headers=headers)
    assert resp.status_code == 200
    out = resp.json()
    assert out["title"] == "Host incident"
    assert out["status"] in ("complete", "partial")


def test_create_report_rejects_an_invalid_kind(client: Any) -> None:
    body = {
        "kind": "not-a-real-kind", "subject_type": "host", "subject_id": "web01",
        "title": "t", "requested_by": str(uuid.uuid4()),
    }
    headers = {"authorization": f"Bearer {token()}"}
    assert client.post(_BASE, json=body, headers=headers).status_code == 422


def test_get_report_requires_a_bearer_token(client: Any) -> None:
    assert client.get(f"{_BASE}/{uuid.uuid4()}").status_code == 401


def test_get_report_404_for_an_unknown_id(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.get(f"{_BASE}/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_get_report_returns_a_presigned_download_url(client: Any) -> None:
    tenant_id = uuid.uuid4()
    headers = {"authorization": f"Bearer {token(tenant=tenant_id)}"}
    create_body = {
        "kind": "incident", "subject_type": "host", "subject_id": "web01",
        "title": "t", "requested_by": str(uuid.uuid4()),
    }
    created = client.post(_BASE, json=create_body, headers=headers).json()

    resp = client.get(f"{_BASE}/{created['id']}", headers=headers)
    assert resp.status_code == 200
    out = resp.json()
    assert out["report"]["id"] == created["id"]
    assert out["download_url"] is not None
    assert out["download_url"].startswith("https://minio.example/")


def test_get_report_from_another_tenant_is_not_found(client: Any) -> None:
    headers = {"authorization": f"Bearer {token(tenant=uuid.uuid4())}"}
    create_body = {
        "kind": "incident", "subject_type": "host", "subject_id": "web01",
        "title": "t", "requested_by": str(uuid.uuid4()),
    }
    created = client.post(_BASE, json=create_body, headers=headers).json()

    other_headers = {"authorization": f"Bearer {token(tenant=uuid.uuid4())}"}
    resp = client.get(f"{_BASE}/{created['id']}", headers=other_headers)
    assert resp.status_code == 404
