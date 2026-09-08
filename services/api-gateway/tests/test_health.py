from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_never_touches_dependencies(client: TestClient, fixture):
    fixture.db.healthy = False
    fixture.cache.healthy = False
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "api-gateway"


def test_readyz_ok(client: TestClient):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert {d["name"] for d in body["dependencies"]} == {"postgres", "redis"}


def test_readyz_returns_503_when_a_required_dependency_is_down(
    client: TestClient, fixture
):
    fixture.db.healthy = False
    r = client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    pg = next(d for d in body["dependencies"] if d["name"] == "postgres")
    assert pg["healthy"] is False
    assert pg["detail"] == "ConnectionError"


def test_meta(client: TestClient):
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["api_version"] == "v1"
    assert body["service"] == "api-gateway"
    assert body["environment"] == "local"


def test_health_deps_requires_authentication(client: TestClient):
    r = client.get("/health/deps")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_health_deps_requires_ops_read(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_analyst.email)  # analyst lacks ops:read
    r = client.get("/health/deps")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "permission_denied"


def test_health_deps_allowed_for_operator(client: TestClient, fixture, do_login):
    do_login("acme", fixture.acme_admin.email)
    r = client.get("/health/deps")
    assert r.status_code == 200
    assert r.json()["ready"] is True


def test_security_headers_and_request_id(client: TestClient):
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-request-id"]
