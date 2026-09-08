from __future__ import annotations

from fastapi.testclient import TestClient


def test_no_session_is_unauthenticated(client: TestClient):
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_unknown_session_cookie_is_unauthenticated(client: TestClient):
    client.cookies.set("sm_session", "does-not-exist")
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 401


def test_missing_permission_is_denied_and_audited(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_analyst.email)  # analyst lacks users:read
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "permission_denied"
    assert "authz.denied" in fixture.audit.actions()
    denial = fixture.audit.entries[-1]
    assert denial["result"] == "deny"
    assert denial["resource_id"] == "users:read"


def test_granted_permission_allows_access(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200
    assert r.json()["limit"] == 50


def test_unsafe_method_without_csrf_is_denied(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    r = client.post(
        "/api/v1/admin/users",
        json={"email": "new@acme-corp.com", "display_name": "New"},
    )
    assert r.status_code == 403
    assert "CSRF" in r.json()["error"]["message"]


def test_unsafe_method_with_wrong_csrf_is_denied(client: TestClient, fixture, do_login, csrf):
    do_login("acme", fixture.acme_admin.email)
    r = client.post(
        "/api/v1/admin/users",
        json={"email": "new@acme-corp.com", "display_name": "New"},
        headers={"x-csrf-token": "not-the-token"},
    )
    assert r.status_code == 403


def test_unsafe_method_with_csrf_succeeds(client: TestClient, fixture, do_login, csrf):
    r = do_login("acme", fixture.acme_admin.email)
    created = client.post(
        "/api/v1/admin/users",
        json={"email": "New@Acme-Corp.com", "display_name": "New"},
        headers=csrf(r),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["email"] == "new@acme-corp.com"  # normalized to lower case
    assert body["status"] == "invited"
    assert body["tenant_id"] == str(fixture.acme.id)
    assert "admin.user.create" in fixture.audit.actions()


def test_duplicate_email_conflicts(client: TestClient, fixture, do_login, csrf):
    r = do_login("acme", fixture.acme_admin.email)
    dup = client.post(
        "/api/v1/admin/users",
        json={"email": fixture.acme_admin.email, "display_name": "Dup"},
        headers=csrf(r),
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"


def test_unknown_role_name_is_not_found(client: TestClient, fixture, do_login, csrf):
    r = do_login("acme", fixture.acme_admin.email)
    bad = client.post(
        "/api/v1/admin/users",
        json={"email": "x@acme-corp.com", "display_name": "X", "role_names": ["no-such-role"]},
        headers=csrf(r),
    )
    assert bad.status_code == 404


def test_revoked_role_takes_effect_on_the_next_request(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    assert client.get("/api/v1/admin/users").status_code == 200

    # Permissions are re-resolved per request, so revocation is immediate even
    # though the session cookie is unchanged.
    fixture.store.user_roles = {
        (u, r) for (u, r) in fixture.store.user_roles if u != fixture.acme_admin.id
    }
    assert client.get("/api/v1/admin/users").status_code == 403


def test_deactivated_user_session_is_dropped(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    fixture.acme_admin.status = "disabled"
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 401


def test_roles_listing_requires_roles_read(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_analyst.email)
    assert client.get("/api/v1/admin/roles").status_code == 403


def test_invalid_cursor_rejected(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    r = client.get("/api/v1/admin/users", params={"cursor": "not-a-uuid"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_limit_is_capped(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    r = client.get("/api/v1/admin/users", params={"limit": 1000})
    assert r.status_code == 422
