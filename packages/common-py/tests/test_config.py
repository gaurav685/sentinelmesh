from __future__ import annotations

import pytest
from pydantic import ValidationError

from sm_common.config import AppSettings, Environment, ResponseMode


def _settings(**over: str) -> AppSettings:
    env = {
        "service_name": "svc",
        "pg_password": "x",
        "internal_jwt_signing_key": "k",
        "oidc_client_secret": "s",
    }
    env.update(over)
    return AppSettings(_env_file=None, **env)  # type: ignore[arg-type]


def test_defaults_local():
    s = _settings()
    assert s.env is Environment.local
    assert s.deployment_profile == "monolith"
    assert s.response_mode is ResponseMode.suggest_only
    assert s.cors_origins_list == ["http://localhost:3000"]
    assert s.pg_dsn.startswith("postgresql+asyncpg://sentinelmesh:x@")


def test_service_name_required():
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None)  # type: ignore[call-arg]


def test_pool_bounds_enforced():
    with pytest.raises(ValidationError):
        _settings(pg_pool_min="5", pg_pool_max="2")


def test_production_rejects_cors_wildcard():
    with pytest.raises(ValidationError) as ei:
        _settings(env="production", cors_allowed_origins="*", kafka_security_protocol="SASL_SSL")
    assert "CORS" in str(ei.value)


def test_production_requires_secrets():
    with pytest.raises(ValidationError):
        AppSettings(  # type: ignore[call-arg]
            _env_file=None,
            service_name="svc",
            env="production",
            cors_allowed_origins="https://app.example.com",
            kafka_security_protocol="SASL_SSL",
        )


def test_production_requires_neo4j_password():
    with pytest.raises(ValidationError, match="SM_NEO4J_PASSWORD"):
        _settings(
            env="production",
            cors_allowed_origins="https://app.example.com",
            kafka_security_protocol="SASL_SSL",
        )


def test_production_ok_with_all_secrets():
    s = _settings(
        env="production",
        cors_allowed_origins="https://app.example.com",
        kafka_security_protocol="SASL_SSL",
        neo4j_password="n",
    )
    assert s.is_production


def test_response_auto_only_in_production():
    with pytest.raises(ValidationError):
        _settings(response_mode="auto")


def test_response_auto_production_needs_policy():
    with pytest.raises(ValidationError):
        _settings(
            env="production",
            response_mode="auto",
            cors_allowed_origins="https://a.example.com",
            kafka_security_protocol="SASL_SSL",
        )


def test_redis_view_key_prefixing():
    s = _settings(redis_key_prefix="sm")
    assert s.redis.key("session", "abc") == "sm:session:abc"


def test_frozen():
    s = _settings()
    with pytest.raises(ValidationError):
        s.service_name = "other"  # type: ignore[misc]
