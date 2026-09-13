"""Authorization security tests (Engineering Constitution A§5/§6, ADR-016).

Tests: permission denial, privilege escalation, deny-by-default across routes,
client-supplied role/permission fields ignored, ops-gated routes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import SecurityFixture

_ADMIN_ROUTES_REQUIRING_USERS_READ = [
    "/api/v1/admin/users",
    "/api/v1/admin/roles",
]

_PASSWORD = "TestP@ss1!"


@pytest.mark.security
def test_unauthenticated_cannot_access_admin_routes(sec_client: TestClient) -> None:
    for path in _ADMIN_ROUTES_REQUIRING_USERS_READ:
        r = sec_client.get(path)
        assert r.status_code == 401, f"Expected 401 for {path}, got {r.status_code}"


@pytest.mark.security
def test_unauthenticated_cannot_access_me(sec_client: TestClient) -> None:
    r = sec_client.get("/api/v1/me")
    assert r.status_code == 401


@pytest.mark.security
def test_analyst_cannot_read_users(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """An analyst does not hold users:read and must be denied."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_analyst.email, "password": _PASSWORD},
    )
    r = sec_client.get("/api/v1/admin/users")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "permission_denied"


@pytest.mark.security
def test_analyst_cannot_create_users(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Analyst lacks users:create."""
    login = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_analyst.email, "password": _PASSWORD},
    )
    csrf = {"x-csrf-token": login.headers["x-csrf-token"]}
    r = sec_client.post(
        "/api/v1/admin/users",
        json={"email": "new@acme-corp.com", "display_name": "New"},
        headers=csrf,
    )
    assert r.status_code == 403


@pytest.mark.security
def test_analyst_cannot_access_benchmark_results(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """ops:read is not in the analyst role."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_analyst.email, "password": _PASSWORD},
    )
    r = sec_client.get("/api/v1/soc/benchmarks")
    assert r.status_code == 403


@pytest.mark.security
def test_admin_can_read_users(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Sanity: a real admin with users:read must succeed."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    r = sec_client.get("/api/v1/admin/users")
    assert r.status_code == 200


@pytest.mark.security
def test_permission_denial_is_audited(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """A denied request must create an audit entry with result=deny."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_analyst.email, "password": _PASSWORD},
    )
    sec_client.get("/api/v1/admin/users")
    denial = sec_fixture.audit.last()
    assert denial["result"] == "deny"
    assert denial["action"] == "authz.denied"


@pytest.mark.security
def test_client_supplied_role_field_in_login_body_is_rejected(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """A login request body that includes an extra `role` field must be rejected
    with a validation error, never silently accepted."""
    r = sec_client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "acme",
            "email": sec_fixture.acme_analyst.email,
            "password": _PASSWORD,
            "role": "tenant_admin",
        },
    )
    assert r.status_code == 422


@pytest.mark.security
def test_client_supplied_permissions_field_in_login_body_is_rejected(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    r = sec_client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "acme",
            "email": sec_fixture.acme_analyst.email,
            "password": _PASSWORD,
            "permissions": ["users:read", "users:create"],
        },
    )
    assert r.status_code == 422


@pytest.mark.security
def test_health_endpoints_do_not_require_auth(sec_client: TestClient) -> None:
    """Liveness and readiness probes must be publicly accessible."""
    for path in ("/healthz", "/readyz"):
        r = sec_client.get(path)
        assert r.status_code in (200, 503), f"Unexpected {r.status_code} for {path}"


@pytest.mark.security
def test_metrics_endpoint_requires_no_auth_but_returns_text(sec_client: TestClient) -> None:
    """/metrics is a Prometheus scrape endpoint — must return 200 with text/plain."""
    r = sec_client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")