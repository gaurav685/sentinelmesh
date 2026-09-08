from __future__ import annotations

from fastapi.testclient import TestClient

from sm_contracts.enums import TenantStatus, UserStatus

GENERIC = "invalid email or password"


def test_login_success_sets_cookies_and_returns_permissions(client: TestClient, fixture, do_login, csrf, password):
    r = do_login("acme", fixture.acme_admin.email)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == fixture.acme_admin.email
    assert "users:read" in body["permissions"]
    assert "password" not in r.text.lower()

    assert client.cookies.get("sm_session")
    assert client.cookies.get("sm_csrf")
    assert r.headers["x-csrf-token"]

    assert "auth.login.local" in fixture.audit.actions()
    assert fixture.audit.last()["result"] == "success"


def test_login_resets_failure_counter(client: TestClient, fixture, do_login):
    fixture.acme_admin.failed_login_count = 2
    do_login("acme", fixture.acme_admin.email)
    assert fixture.acme_admin.failed_login_count == 0
    assert fixture.acme_admin.last_login_at is not None


def test_wrong_password_is_generic_and_audited(client: TestClient, fixture, do_login, password):
    r = do_login("acme", fixture.acme_admin.email, password="wrong")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    assert r.json()["error"]["message"] == GENERIC
    assert fixture.audit.last()["result"] == "failure"
    assert fixture.audit.last()["meta"]["reason"] == "bad_password"


def test_unknown_user_and_unknown_tenant_are_indistinguishable(client: TestClient, fixture, do_login, password):
    a = do_login("acme", "nobody@acme-corp.com")
    b = do_login("no-such-tenant", "nobody@acme-corp.com")
    c = do_login("acme", fixture.acme_admin.email, password="wrong")
    bodies = [x.json()["error"]["message"] for x in (a, b, c)]
    codes = [x.json()["error"]["code"] for x in (a, b, c)]
    statuses = [x.status_code for x in (a, b, c)]
    assert bodies == [GENERIC] * 3
    assert codes == ["invalid_credentials"] * 3
    assert statuses == [401] * 3


def test_lockout_after_threshold(client: TestClient, fixture, do_login, password):
    # settings fixture sets login_max_failures = 3
    for _ in range(3):
        do_login("acme", fixture.acme_admin.email, password="wrong")
    assert fixture.acme_admin.locked_until is not None

    # the correct password now also fails, and the reason is recorded as locked
    r = do_login("acme", fixture.acme_admin.email, password=password)
    assert r.status_code == 401
    assert fixture.audit.last()["meta"]["reason"] == "account_locked"


def test_suspended_tenant_rejected(client: TestClient, fixture, do_login):
    fixture.acme.status = TenantStatus.suspended.value
    r = do_login("acme", fixture.acme_admin.email)
    assert r.status_code == 401
    assert fixture.audit.last()["meta"]["reason"] == "unknown_or_inactive_tenant"


def test_non_active_user_rejected(client: TestClient, fixture, do_login):
    fixture.acme_admin.status = UserStatus.invited.value
    r = do_login("acme", fixture.acme_admin.email)
    assert r.status_code == 401
    assert fixture.audit.last()["meta"]["reason"] == "user_not_active"


def test_federated_only_account_cannot_use_local_login(client: TestClient, fixture, do_login):
    fixture.acme_admin.password_hash = None
    r = do_login("acme", fixture.acme_admin.email)
    assert r.status_code == 401
    assert fixture.audit.last()["meta"]["reason"] == "no_local_password"


def test_invalid_payload_returns_canonical_validation_error(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"tenant_slug": "acme", "email": "not-an-email"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]


def test_unknown_field_rejected(client: TestClient, fixture, password):
    r = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "acme",
            "email": fixture.acme_admin.email,
            "password": password,
            "is_admin": True,
        },
    )
    assert r.status_code == 422


def test_me_returns_own_tenant_and_permissions(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    r = client.get("/api/v1/me")
    assert r.status_code == 200
    body = r.json()
    assert body["tenant"]["slug"] == "acme"
    assert body["user"]["email"] == fixture.acme_admin.email
    assert body["roles"] == ["tenant_admin"]
    assert "users:read" in body["permissions"]


def test_logout_clears_session(client: TestClient, fixture, do_login, csrf):
    r = do_login("acme", fixture.acme_admin.email)
    out = client.post("/api/v1/auth/logout", headers=csrf(r))
    assert out.status_code == 200
    assert out.json()["ok"] is True
    assert client.get("/api/v1/me").status_code == 401
    assert "auth.logout" in fixture.audit.actions()
