from __future__ import annotations

from fastapi.testclient import TestClient


def test_requests_under_the_limit_pass(make_client):
    client: TestClient = make_client(rate_limit_per_minute=3)
    for _ in range(3):
        assert client.get("/api/v1/meta").status_code == 200


def test_request_over_the_limit_is_429_with_retry_after(make_client):
    client: TestClient = make_client(rate_limit_per_minute=3)
    for _ in range(3):
        client.get("/api/v1/meta")
    r = client.get("/api/v1/meta")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 0
    assert r.json()["error"]["request_id"]


def test_health_and_metrics_are_never_limited(make_client):
    client: TestClient = make_client(rate_limit_per_minute=2)
    for _ in range(20):
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code in (200, 503)
        assert client.get("/metrics").status_code == 200


def test_limiter_fails_open_when_redis_is_down(fixture, make_client):
    client: TestClient = make_client(rate_limit_per_minute=3)
    fixture.cache.client.healthy = False
    for _ in range(10):
        assert client.get("/api/v1/meta").status_code == 200
    body = fixture.services.metrics.render_latest()
    assert b"sm_rate_limiter_errors_total" in body


def test_a_429_is_counted(fixture, make_client):
    client: TestClient = make_client(rate_limit_per_minute=2)
    for _ in range(5):
        client.get("/api/v1/meta")
    body = fixture.services.metrics.render_latest()
    assert b"sm_rate_limited_total" in body
