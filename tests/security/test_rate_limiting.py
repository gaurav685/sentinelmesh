"""Rate limiting security tests (Engineering Constitution A§5, ADR-016).

Tests: rate limit enforcement (HTTP 429), retry-after header accuracy,
anti-spoofing against X-Forwarded-For header manipulation, exemption of health
and metrics endpoints, and fail-open behavior during cache disruption.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import build_security_fixture

from sm_api_gateway.app import create_app


@pytest.mark.security
def test_rate_limit_exceeded_returns_429() -> None:
    """A client exceeding the rate limit receives 429 Too Many Requests."""
    fix = build_security_fixture(rate_limit_per_minute=3)
    app = create_app(services=fix.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        for _ in range(3):
            r = c.get("/api/v1/meta")
            assert r.status_code == 200
        # 4th request must be rejected
        blocked = c.get("/api/v1/meta")
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "rate_limited"
        assert "retry-after" in blocked.headers
        assert int(blocked.headers["retry-after"]) >= 0


@pytest.mark.security
def test_client_ip_spoofing_via_forwarded_for_fails_with_zero_hops() -> None:
    """When trusted_proxy_hops is 0 (default), spoofing X-Forwarded-For cannot evade
    the rate limit."""
    fix = build_security_fixture(rate_limit_per_minute=2, trusted_proxy_hops=0)
    app = create_app(services=fix.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        # Request 1 with IP A
        r1 = c.get("/api/v1/meta", headers={"x-forwarded-for": "198.51.100.1"})
        assert r1.status_code == 200
        # Request 2 with IP B
        r2 = c.get("/api/v1/meta", headers={"x-forwarded-for": "198.51.100.2"})
        assert r2.status_code == 200
        # Request 3 with IP C - must still be rate-limited because peer IP is the same
        r3 = c.get("/api/v1/meta", headers={"x-forwarded-for": "198.51.100.3"})
        assert r3.status_code == 429
        assert r3.json()["error"]["code"] == "rate_limited"


@pytest.mark.security
def test_rate_limiting_exempt_routes_accessible_during_lockout() -> None:
    """Liveness, readiness, and metrics endpoints are never rate limited, ensuring
    monitoring and orchestrator probes never fail due to API floods."""
    fix = build_security_fixture(rate_limit_per_minute=2)
    app = create_app(services=fix.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        # Exhaust the rate limit
        for _ in range(5):
            c.get("/api/v1/meta")

        # Exemption check
        for _ in range(10):
            assert c.get("/healthz").status_code == 200
            assert c.get("/metrics").status_code == 200


@pytest.mark.security
def test_rate_limit_fails_open_when_cache_unhealthy() -> None:
    """When Redis is temporarily unavailable, API gateway fails open rather than
    imposing an unintended global denial of service on analysts."""
    fix = build_security_fixture(rate_limit_per_minute=2)
    fix.cache.client.healthy = False
    app = create_app(services=fix.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        for _ in range(5):
            assert c.get("/api/v1/meta").status_code == 200
        # Metrics record the limiter error
        body = fix.services.metrics.render_latest()
        assert b"sm_rate_limiter_errors_total" in body