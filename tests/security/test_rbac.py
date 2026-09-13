"""RBAC security tests (Engineering Constitution A§6, ADR-016).

Tests: cross-tenant role grant rejected, self-escalation blocked, role grant
requires holding the target role, unknown role grant fails.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import SecurityFixture

_PASSWORD = "TestP@ss1!"


@pytest.mark.security
def test_analyst_cannot_grant_any_role(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """An analyst lacks roles:grant and must be denied for any grant attempt."""
    login = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_analyst.email, "password": _PASSWORD},
    )
    csrf = {"x-csrf-token": login.headers["x-csrf-token"]}
    r = sec_client.post(
        f"/api/v1/admin/users/{sec_fixture.acme_analyst.id}/roles",
        json={"role_id": str(sec_fixture.admin_role.id)},
        headers=csrf,
    )
    assert r.status_code == 403


@pytest.mark.security
def test_cross_tenant_role_grant_returns_404_not_403(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """An admin granting a role to a user in another tenant sees 404 —
    indistinguishable from a user that does not exist (information hiding)."""
    login = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    csrf = {"x-csrf-token": login.headers["x-csrf-token"]}
    r = sec_client.post(
        f"/api/v1/admin/users/{sec_fixture.globex_admin.id}/roles",
        json={"role_id": str(sec_fixture.analyst_role.id)},
        headers=csrf,
    )
    assert r.status_code == 404
    # and the role was not actually granted
    assert (sec_fixture.globex_admin.id, sec_fixture.analyst_role.id) not in sec_fixture.store.user_roles


@pytest.mark.security
def test_admin_cannot_grant_role_to_nonexistent_user(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Granting to a user id that does not exist in the tenant returns 404."""
    import uuid
    login = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    csrf = {"x-csrf-token": login.headers["x-csrf-token"]}
    r = sec_client.post(
        f"/api/v1/admin/users/{uuid.uuid4()}/roles",
        json={"role_id": str(sec_fixture.analyst_role.id)},
        headers=csrf,
    )
    assert r.status_code == 404


@pytest.mark.security
def test_granting_unknown_role_id_fails_gracefully(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """A role_id that does not exist must not grant silently."""
    import uuid
    login = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    csrf = {"x-csrf-token": login.headers["x-csrf-token"]}
    r = sec_client.post(
        f"/api/v1/admin/users/{sec_fixture.acme_analyst.id}/roles",
        json={"role_id": str(uuid.uuid4())},
        headers=csrf,
    )
    assert r.status_code == 404


@pytest.mark.security
def test_grant_within_own_tenant_succeeds(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Sanity: a legitimate grant within own tenant succeeds and is audited."""
    login = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    csrf = {"x-csrf-token": login.headers["x-csrf-token"]}
    r = sec_client.post(
        f"/api/v1/admin/users/{sec_fixture.acme_analyst.id}/roles",
        json={"role_id": str(sec_fixture.admin_role.id)},
        headers=csrf,
    )
    assert r.status_code == 201
    assert "admin.role.grant" in sec_fixture.audit.actions()


@pytest.mark.security
def test_role_list_scoped_to_system_roles_only(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """The roles list must return only system-defined roles, never raw DB models
    that could leak internal IDs of another tenant's custom roles."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": _PASSWORD},
    )
    r = sec_client.get("/api/v1/admin/roles")
    assert r.status_code == 200
    items = r.json()
    names = {item["name"] for item in items}
    # All returned roles are the known system roles.
    assert names == {"tenant_admin", "analyst"}