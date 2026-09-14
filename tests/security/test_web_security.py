"""Web security tests (Engineering Constitution A§5, ADR-016).

Tests: CSRF protection on state-changing methods, CSRF exemption on safe methods,
XSS mitigation via JSON content-type and encoding, security response headers,
path traversal rejection, and body size limits.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import _PASSWORD, SecurityFixture

from sm_api_gateway.app import create_app


@pytest.mark.security
def test_state_changing_post_requires_csrf_token(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """A mutating POST request with a valid session but missing x-csrf-token is rejected with 403."""
    login_resp = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    assert login_resp.status_code == 200

    # Attempt to grant role WITHOUT providing x-csrf-token header
    r = sec_client.post(
        f"/api/v1/admin/users/{sec_fixture.acme_analyst.id}/roles",
        json={"role_id": str(sec_fixture.admin_role.id)},
    )
    assert r.status_code == 403
    assert "csrf" in r.json()["error"]["message"].lower()


@pytest.mark.security
def test_forged_csrf_token_is_rejected(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """A mutating POST request with an invalid/tampered x-csrf-token is rejected with 403."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    r = sec_client.post(
        f"/api/v1/admin/users/{sec_fixture.acme_analyst.id}/roles",
        json={"role_id": str(sec_fixture.admin_role.id)},
        headers={"x-csrf-token": "completely-forged-csrf-token"},
    )
    assert r.status_code == 403
    assert "csrf" in r.json()["error"]["message"].lower()


@pytest.mark.security
def test_valid_csrf_token_is_accepted(
    sec_client: TestClient, sec_fixture: SecurityFixture, sec_csrf: object
) -> None:
    """A mutating POST request with the genuine x-csrf-token from login succeeds."""
    login_resp = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    assert login_resp.status_code == 200
    csrf_token = login_resp.headers["x-csrf-token"]

    r = sec_client.post(
        f"/api/v1/admin/users/{sec_fixture.acme_analyst.id}/roles",
        json={"role_id": str(sec_fixture.admin_role.id)},
        headers={"x-csrf-token": csrf_token},
    )
    assert r.status_code == 201


@pytest.mark.security
def test_safe_get_method_requires_no_csrf_token(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Safe read-only methods (GET) do not require a CSRF token."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    r = sec_client.get("/api/v1/me")
    assert r.status_code == 200
    r_users = sec_client.get("/api/v1/admin/users")
    assert r_users.status_code == 200


@pytest.mark.security
def test_security_headers_present_on_all_responses(sec_client: TestClient) -> None:
    """SecurityHeadersMiddleware applies mandatory hardening headers."""
    r = sec_client.get("/healthz")
    assert r.status_code == 200
    headers = {k.lower(): v for k, v in r.headers.items()}
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "no-referrer"
    assert "geolocation=()" in headers.get("permissions-policy", "")
    assert headers.get("cross-origin-opener-policy") == "same-origin"
    assert "default-src 'none'" in headers.get("content-security-policy", "")


@pytest.mark.security
def test_xss_payload_in_user_display_name_is_json_encoded(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Input containing HTML script tags is rendered strictly as JSON text, not HTML."""
    login_resp = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    csrf_token = login_resp.headers["x-csrf-token"]
    xss_name = "<script>alert('xss')</script>"
    r = sec_client.post(
        "/api/v1/admin/users",
        json={"email": "xss_test@acme-corp.com", "display_name": xss_name},
        headers={"x-csrf-token": csrf_token},
    )
    assert r.status_code == 201
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert data["display_name"] == xss_name


@pytest.mark.security
def test_path_traversal_in_resource_identifiers_is_rejected_or_not_found(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Path traversal sequences (../../) in path parameters cannot escape API routes."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    traversal_ids = [
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "..\\..\\windows\\win.ini",
    ]
    for tid in traversal_ids:
        r = sec_client.get(f"/api/v1/soc/reports/{tid}")
        # Must return 400, 404, or 422 - never 200 or 500
        assert r.status_code in (400, 404, 422)


@pytest.mark.security
def test_body_size_limit_rejects_oversized_payloads(
    sec_fixture: SecurityFixture,
) -> None:
    """BodySizeLimitMiddleware rejects requests whose Content-Length exceeds the limit."""
    app = create_app(services=sec_fixture.services)
    # The default app already includes BodySizeLimitMiddleware(max_bytes=settings.http_max_body_bytes)
    with TestClient(app, raise_server_exceptions=False) as c:
        oversized_len = sec_fixture.services.settings.http_max_body_bytes + 1024
        r = c.post(
            "/api/v1/auth/login",
            content=b"x" * 100,
            headers={
                "content-type": "application/json",
                "content-length": str(oversized_len),
            },
        )
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "payload_too_large"