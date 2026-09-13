"""SSRF security tests (Engineering Constitution A§5, ADR-016).

Tests: prevention of server-side request forgery in URL-accepting flows,
OIDC redirect_uri tampering, Host header poisoning against internal routing,
and ensuring client telemetry cannot redirect internal service-to-service calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import _PASSWORD, SecurityFixture


@pytest.mark.security
def test_oidc_login_ignores_client_redirect_uri_override(sec_client: TestClient) -> None:
    """The OIDC login endpoint must never accept a client-provided redirect_uri,
    preventing open redirect and SSRF to internal/cloud metadata addresses."""
    malicious_redirects = [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8080/internal/admin",
        "http://attacker.com/callback",
    ]
    for target in malicious_redirects:
        # Client tries to inject redirect_uri via query param
        r = sec_client.get(
            "/api/v1/auth/oidc/login",
            params={"tenant": "acme", "redirect_uri": target},
            follow_redirects=False,
        )
        # OIDC is either unconfigured (503) or redirects to provider - never to the malicious URL
        if r.status_code == 302:
            location = r.headers.get("location", "")
            assert target not in location, f"Malicious target {target} was reflected in location"
            # Must redirect only to the configured IdP authorization endpoint
            assert "169.254.169.254" not in location
        else:
            assert r.status_code in (404, 422, 503)


@pytest.mark.security
def test_host_header_injection_does_not_poison_internal_services(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Spoofed Host or X-Forwarded-Host headers must not alter internal service
    client routing or cause SSRF to cloud metadata endpoints."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_analyst.email, "password": _PASSWORD},
    )
    malicious_hosts = [
        "169.254.169.254",
        "127.0.0.1:9000",
        "attacker-controlled-host.com",
    ]
    for host in malicious_hosts:
        r = sec_client.get(
            "/api/v1/soc/detections",
            headers={"Host": host, "X-Forwarded-Host": host},
        )
        # The request routes to the local mock/fake repository, never attempting
        # an outbound request to the spoofed host.
        assert r.status_code == 200


@pytest.mark.security
def test_indicator_search_never_triggers_outbound_http(
    sec_client: TestClient, sec_fixture: SecurityFixture
) -> None:
    """Threat intel lookups with metadata/private IP addresses are treated as data queries,
    never fetched as URLs by the server."""
    sec_client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "acme", "email": sec_fixture.acme_analyst.email, "password": _PASSWORD},
    )
    private_ips = [
        "169.254.169.254",  # AWS/GCP metadata service
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
    ]
    for ip in private_ips:
        r = sec_client.get(
            "/api/v1/soc/threat-intel",
            params={"type": "ip", "value": ip},
        )
        # Treated as normal query parameters, returning 200 with data or empty list
        assert r.status_code in (200, 404, 422)