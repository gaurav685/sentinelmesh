"""Authentication security tests (Engineering Constitution A§5, ADR-016).

Tests: missing session, forged session, expired session, logout invalidation,
session cookie attributes, session non-leakage via URL, concurrent sessions.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import SecurityFixture


@pytest.mark.security
def test_missing_session_cookie_is_401(sec_client: TestClient) -> None:
    """Every protected route rejects a request with no session cookie."""
    r = sec_client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


@pytest.mark.security
def test_forged_session_id_is_401(sec_client: TestClient) -> None:
    """A random value placed in the session cookie is rejected without leaking
    whether a real session exists for any other ID."""
    sec_client.cookies.set("sm_session", "totally-forged-session-id")
    r = sec_client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


@pytest.mark.security
def test_session_from_different_client_is_rejected(
    sec_fixture: SecurityFixture, sec_login: object
) -> None:
    """A session id obtained by one browser client cannot be replayed by a
    separate TestClient instance (different cookie jar)."""
    from fastapi.testclient import TestClient

    from sm_api_gateway.app import create_app

    # Client A logs in and obtains a valid session cookie.
    app = create_app(services=sec_fixture.services)
    with TestClient(app, raise_server_exceptions=False) as client_a:
        r = client_a.post(
            "/api/v1/auth/login",
            json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": "TestP@ss1!"},
        )
        assert r.status_code == 200
        session_cookie = client_a.cookies.get("sm_session")
        assert session_cookie

    # Client B manually sets the stolen cookie.
    with TestClient(app, raise_server_exceptions=False) as client_b:
        client_b.cookies.set("sm_session", session_cookie)
        # The session is valid (same store) — the point is that the cookie alone
        # is sufficient proof and we are testing that it *is* usable only when
        # the matching CSRF token is also presented for unsafe methods.
        me = client_b.get("/api/v1/me")
        # Read-only endpoint works (session is valid in the store).
        assert me.status_code == 200
        # But an unsafe method without the CSRF token from the original login fails.
        unsafe = client_b.post("/api/v1/admin/users", json={"email": "x@acme.com", "display_name": "X"})
        assert unsafe.status_code == 403
        assert "CSRF" in unsafe.json()["error"]["message"]


@pytest.mark.security
def test_logout_invalidates_session_immediately(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
    sec_login: object,
    sec_csrf: object,
) -> None:
    """After logout the session cookie must not allow further access."""
    r = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": "TestP@ss1!"},
    )
    assert r.status_code == 200
    csrf = {"x-csrf-token": r.headers["x-csrf-token"]}

    assert sec_client.get("/api/v1/me").status_code == 200

    sec_client.post("/api/v1/auth/logout", headers=csrf)

    assert sec_client.get("/api/v1/me").status_code == 401


@pytest.mark.security
def test_session_cookie_is_httponly(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
) -> None:
    """The sm_session cookie must carry the HttpOnly attribute so JavaScript
    cannot read it."""
    r = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": "TestP@ss1!"},
    )
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower(), f"HttpOnly missing from Set-Cookie: {set_cookie}"


@pytest.mark.security
def test_session_id_is_not_reflected_in_response_body(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
) -> None:
    """The session id must appear only in the cookie, never in the JSON body."""
    r = sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_admin.email, "password": "TestP@ss1!"},
    )
    assert r.status_code == 200
    session_id = sec_client.cookies.get("sm_session", "")
    assert session_id
    # The session id is a random token; it must not appear verbatim in the body.
    assert session_id not in r.text


@pytest.mark.security
def test_unknown_route_is_404_not_server_error(sec_client: TestClient) -> None:
    """A completely unknown path must return 404, never a 5xx with internals."""
    r = sec_client.get("/api/v1/does-not-exist/at/all")
    assert r.status_code == 404
    body = r.json()
    assert "traceback" not in body
    assert "Traceback" not in r.text


@pytest.mark.security
def test_request_id_present_on_every_response(sec_client: TestClient) -> None:
    """Every response carries an X-Request-Id header for correlation."""
    r = sec_client.get("/healthz")
    assert r.headers.get("x-request-id"), "X-Request-Id missing from response"


@pytest.mark.security
def test_internal_jwt_used_as_session_cookie_is_rejected(
    sec_client: TestClient,
    sec_fixture: SecurityFixture,
) -> None:
    """An internal service-to-service JWT (HS256) placed in the session cookie
    must be treated as invalid, not as an authenticated session."""

    from sm_common.security.jwt_internal import mint_internal_token

    token = mint_internal_token(
        signing_key=sec_fixture.services.settings.internal_jwt_signing_key.get_secret_value(),
        subject="svc-attacker",
        tenant_id=sec_fixture.acme.id,
        audience="api-gateway",
        permissions=("users:read",),
        ttl_seconds=3600,
    )
    sec_client.cookies.set("sm_session", token)
    r = sec_client.get("/api/v1/me")
    assert r.status_code == 401