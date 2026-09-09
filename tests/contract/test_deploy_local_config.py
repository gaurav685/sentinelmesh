"""Offline checks on the local deployment definitions.

`docker compose config` would validate these properly, but Docker is not a
prerequisite for running the test suite. These assertions cover the mistakes
that actually bite: a container pointed at `localhost` instead of a service
name, a missing health gate, a root-running image, a scrape target that does not
match the app's port.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "docker" / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "deploy" / "docker" / "Dockerfile.app"
PROMETHEUS = REPO_ROOT / "deploy" / "prometheus" / "prometheus.yml"
REALM = REPO_ROOT / "deploy" / "docker" / "keycloak" / "realm-sentinelmesh.json"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

DEFAULT_PROFILE_SERVICES = {"postgres", "redis", "migrate", "app"}
PROFILED = {
    "keycloak": "oidc",
    "prometheus": "obs",
    "grafana": "obs",
    "neo4j": "graph",
    "graph-service": "graph",
    "ml-inference": "detect",
    "redpanda": "bus",
    "minio": "objects",
}


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_parses_and_declares_the_expected_services(compose: dict[str, Any]):
    services = compose["services"]
    assert DEFAULT_PROFILE_SERVICES <= set(services)
    assert set(PROFILED) <= set(services)


def test_core_services_are_not_behind_a_profile(compose: dict[str, Any]):
    """`docker compose up` must bring exactly what the integration tests need."""
    for name in DEFAULT_PROFILE_SERVICES:
        assert "profiles" not in compose["services"][name], name


def test_optional_services_are_behind_their_profile(compose: dict[str, Any]):
    for name, profile in PROFILED.items():
        assert compose["services"][name]["profiles"] == [profile], name


def test_containers_address_each_other_by_service_name(compose: dict[str, Any]):
    """A container must never be pointed at localhost — that is the container
    itself, not the dependency."""
    for name in ("app", "migrate"):
        env = compose["services"][name]["environment"]
        rendered = json.dumps(env)
        assert "localhost" not in rendered.replace("http://localhost:3000", ""), name
        assert "127.0.0.1" not in rendered, name
        assert env["SM_PG_HOST"] == "postgres"
        assert env["SM_REDIS_URL"] == "redis://redis:6379/0"
        assert env["SM_OIDC_ISSUER"].startswith("http://keycloak:8080/")
        assert env["SM_NEO4J_URI"] == "bolt://neo4j:7687"
        assert env["SM_KAFKA_BOOTSTRAP_SERVERS"] == "redpanda:9092"
        assert env["SM_S3_ENDPOINT"] == "http://minio:9000"


def test_each_service_has_its_own_service_name_setting(compose: dict[str, Any]):
    assert compose["services"]["app"]["environment"]["SM_SERVICE_NAME"] == "api-gateway"
    assert compose["services"]["migrate"]["environment"]["SM_SERVICE_NAME"] == "migrations"


def test_stateful_dependencies_have_healthchecks(compose: dict[str, Any]):
    for name in ("postgres", "redis", "neo4j"):
        assert "healthcheck" in compose["services"][name], name
        assert compose["services"][name]["healthcheck"]["test"], name


def test_app_waits_for_healthy_dependencies_and_a_successful_migration(compose: dict[str, Any]):
    depends = compose["services"]["app"]["depends_on"]
    assert depends["postgres"]["condition"] == "service_healthy"
    assert depends["redis"]["condition"] == "service_healthy"
    assert depends["migrate"]["condition"] == "service_completed_successfully"


def test_migrate_waits_for_postgres_and_does_not_restart(compose: dict[str, Any]):
    migrate = compose["services"]["migrate"]
    assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert migrate["restart"] == "no"
    assert migrate["command"][:2] == ["alembic", "-c"]
    assert migrate["command"][-2:] == ["upgrade", "head"]


def test_required_secrets_fail_fast_rather_than_defaulting(compose: dict[str, Any]):
    """A missing password must stop compose, not silently start an open database."""
    postgres_password = compose["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert postgres_password.startswith("${SM_PG_PASSWORD:?")


def test_data_volumes_are_declared(compose: dict[str, Any]):
    assert {"postgres-data", "neo4j-data", "minio-data"} <= set(compose["volumes"])


def test_dockerfile_is_multistage_non_root_and_health_checked():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert text.count("FROM ") >= 2, "expected a builder and a runtime stage"
    assert "AS builder" in text
    assert "AS runtime" in text
    assert "USER 10001" in text, "the runtime stage must not run as root"
    assert "HEALTHCHECK" in text
    assert "CMD [\"python\", \"-m\", \"sm_api_gateway\"]" in text
    # No compiler in the runtime stage: build-essential is installed before the
    # runtime FROM and never after it.
    runtime = text.split("AS runtime", 1)[1]
    assert "build-essential" not in runtime


def test_dockerignore_excludes_secrets_and_the_virtualenv():
    text = DOCKERIGNORE.read_text(encoding="utf-8")
    for pattern in (".env", ".venv", ".git"):
        assert pattern in text, pattern
    assert "!.env.example" in text


def test_prometheus_scrapes_the_gateway_on_its_actual_port():
    config = yaml.safe_load(PROMETHEUS.read_text(encoding="utf-8"))
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    gateway = jobs["sentinelmesh-api-gateway"]
    assert gateway["metrics_path"] == "/metrics"
    assert gateway["static_configs"][0]["targets"] == ["app:8000"]


def test_keycloak_realm_client_is_confidential_and_uses_pkce():
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    assert realm["realm"] == "sentinelmesh"
    client = next(c for c in realm["clients"] if c["clientId"] == "sentinelmesh-api")
    assert client["publicClient"] is False
    assert client["standardFlowEnabled"] is True
    assert client["implicitFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False, "password grant must stay off"
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert any(
        uri.endswith("/api/v1/auth/oidc/callback") for uri in client["redirectUris"]
    ), "redirect URIs must be exact callback paths, not wildcards"


def test_keycloak_realm_is_marked_as_development_only():
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    assert "development" in realm["displayName"].lower()
    assert realm["registrationAllowed"] is False
