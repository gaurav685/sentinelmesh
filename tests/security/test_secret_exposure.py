"""Secret exposure security tests (Engineering Constitution A§5, ADR-016).

Tests: audit trail excludes plaintext passwords, error responses never leak
stack traces, internal paths, or credentials, /metrics endpoint contains no
secrets or PII, and AppSettings masks sensitive fields in repr/str.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from tests.conftest import _PASSWORD, SecurityFixture, build_security_fixture

from sm_api_gateway.app import create_app

_CANARY_JWT = "canary-jwt-secret-do-not-leak-999!"
_CANARY_PG = "canary-pg-secret-do-not-leak-888!"


@pytest.mark.security
def test_login_failure_audit_never_records_password(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Failed login attempts audit the event, but never include the supplied password."""
    leaked_canary = "super-secret-canary-password-123!"
    sec_client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "acme",
            "email": sec_fixture.acme_admin.email,
            "password": leaked_canary,
        },
    )
    # Check all audit records produced during this test
    for entry in sec_fixture.audit.entries:
        serialized = json.dumps(entry, default=str)
        assert leaked_canary not in serialized, "Plaintext password leaked into audit entry"
        assert "password" not in entry.get("meta", {}), "Password field present in audit meta"


@pytest.mark.security
def test_error_responses_contain_no_secrets_or_stack_traces() -> None:
    """API error responses conform to canonical structure and never expose stack traces or secrets."""
    fix = build_security_fixture(
        internal_jwt_signing_key=_CANARY_JWT,
        pg_password=_CANARY_PG,
    )
    app = create_app(services=fix.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        # 1. 401 unauthenticated
        r401 = c.get("/api/v1/me")
        assert r401.status_code == 401
        # 2. 404 not found
        r404 = c.get("/api/v1/nonexistent/resource/path")
        assert r404.status_code == 404
        # 3. 422 validation error
        r422 = c.post("/api/v1/auth/login", json={"invalid": "schema"})
        assert r422.status_code == 422

        for r in (r401, r404, r422):
            text = r.text
            assert "Traceback (most recent call last)" not in text
            assert "site-packages" not in text
            assert _CANARY_JWT not in text
            assert _CANARY_PG not in text
            data = r.json()
            assert "error" in data
            assert "code" in data["error"]
            assert "message" in data["error"]


@pytest.mark.security
def test_metrics_endpoint_contains_no_secrets_or_passwords() -> None:
    """The Prometheus /metrics endpoint exposes system telemetry only, no secret credentials."""
    fix = build_security_fixture(
        internal_jwt_signing_key=_CANARY_JWT,
        pg_password=_CANARY_PG,
    )
    app = create_app(services=fix.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/metrics")
        assert r.status_code == 200
        metrics_text = r.text

        assert _CANARY_JWT not in metrics_text
        assert _CANARY_PG not in metrics_text
        assert _PASSWORD not in metrics_text


@pytest.mark.security
def test_app_settings_masks_secrets_in_repr() -> None:
    """Pydantic SecretStr fields in AppSettings are masked in string representations."""
    fix = build_security_fixture(
        internal_jwt_signing_key=_CANARY_JWT,
        pg_password=_CANARY_PG,
    )
    settings = fix.services.settings
    settings_repr = repr(settings)
    settings_str = str(settings)

    # Raw secrets must not appear in string representations of settings
    assert _CANARY_JWT not in settings_repr
    assert _CANARY_PG not in settings_repr
    assert _CANARY_JWT not in settings_str
    assert _CANARY_PG not in settings_str
    assert "**********" in settings_repr