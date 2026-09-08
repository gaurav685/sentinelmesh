from __future__ import annotations

import pytest

from sm_common.cache import Cache, build_redis
from sm_common.config import AppSettings
from sm_common.db import Database, build_engine
from sm_common.observability import build_metrics, configure_tracing, get_tracer


def _settings(**over: str) -> AppSettings:
    env = {
        "service_name": "svc",
        "pg_password": "pw",
        "internal_jwt_signing_key": "k",
        "oidc_client_secret": "s",
    }
    env.update(over)
    return AppSettings(_env_file=None, **env)  # type: ignore[arg-type]


# ---- db --------------------------------------------------------------------
def test_engine_url_and_pool():
    s = _settings(pg_host="db", pg_db="sm", pg_user="app", pg_pool_max="7")
    eng = build_engine(s)
    assert eng.url.drivername == "postgresql+asyncpg"
    assert eng.url.host == "db"
    assert eng.url.database == "sm"
    assert eng.pool.size() == 7  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_database_dispose_is_clean():
    db = Database.from_settings(_settings())
    await db.dispose()  # no connection ever opened; must not raise


# ---- redis ---------------------------------------------------------------
def test_cache_key_prefix():
    c = Cache.from_settings(_settings(redis_key_prefix="sm"))
    assert c.key("session", "abc") == "sm:session:abc"
    assert c.key("ratelimit", "ip", "1m") == "sm:ratelimit:ip:1m"


def test_build_redis_no_connection():
    client = build_redis(_settings(redis_url="redis://cache:6379/1"))
    assert client is not None


# ---- metrics -----------------------------------------------------------
def test_metrics_observe_and_render():
    m = build_metrics("api-gateway")
    m.observe_http("GET", "/api/v1/me", 200, 0.012)
    m.authn_failures.labels("api-gateway", "invalid_credentials").inc()
    body = m.render_latest()
    assert b"sm_http_requests_total" in body
    assert b"sm_authn_failures_total" in body


def test_two_metrics_registries_isolated():
    a = build_metrics("a")
    b = build_metrics("b")
    a.observe_http("GET", "/x", 200, 0.1)
    assert a.registry is not b.registry


# ---- tracing ---------------------------------------------------------
def test_tracing_noop_without_endpoint():
    s = _settings()  # no SM_OTEL_EXPORTER_OTLP_ENDPOINT
    configure_tracing(s)  # must not raise, must not install an exporter
    tracer = get_tracer("test")
    with tracer.start_as_current_span("unit") as span:
        assert span is not None
