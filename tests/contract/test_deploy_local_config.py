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
GRAFANA_DATASOURCE = REPO_ROOT / "deploy" / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
GRAFANA_DASHBOARD_PROVIDER = REPO_ROOT / "deploy" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"
GRAFANA_PROVISIONING_ROOT = REPO_ROOT / "deploy" / "grafana" / "provisioning"
GRAFANA_DASHBOARDS_DIR = GRAFANA_PROVISIONING_ROOT / "dashboards" / "files"
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
    "detection-engine": "detect",
    "mitre-service": "detect",
    "threat-intel-service": "detect",
    "correlation-engine": "detect",
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


def test_prometheus_scrapes_every_backend_service_on_its_actual_port(compose: dict[str, Any]):
    """Every service that gets a real port in docker-compose must also be a
    real Prometheus scrape target (Phase 15 / ADR-020) — a service present in
    one and not the other is a metrics blind spot."""
    config = yaml.safe_load(PROMETHEUS.read_text(encoding="utf-8"))
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    targets = {
        t["labels"]["service"]: t["targets"][0]
        for t in jobs["sentinelmesh-services"]["static_configs"]
    }
    expected = {
        "ingestion-gateway": "ingestion-gateway:8001",
        "normalization-engine": "normalization-engine:8002",
        "stream-processor": "stream-processor:8003",
        "graph-service": "graph-service:8004",
        "ml-inference": "ml-inference:8005",
        "detection-engine": "detection-engine:8006",
        "threat-intel-service": "threat-intel-service:8007",
        "mitre-service": "mitre-service:8008",
        "correlation-engine": "correlation-engine:8009",
        "ai-analyst": "ai-analyst:8010",
        "simulation-service": "simulation-service:8011",
        "memory-service": "memory-service:8012",
        "reporting-service": "reporting-service:8013",
    }
    assert targets == expected
    # every one of these names must be a real compose service, on the port
    # its own docker-compose.yml block actually publishes.
    for service, target in expected.items():
        port = target.rsplit(":", 1)[1]
        published = compose["services"][service]["ports"]
        assert any(p.split(":")[-1] == port for p in published), service


def test_grafana_is_provisioned_with_the_prometheus_datasource():
    """Without this, every fresh `--profile obs up` starts a blank Grafana
    that needs the datasource added by hand before any dashboard renders."""
    config = yaml.safe_load(GRAFANA_DATASOURCE.read_text(encoding="utf-8"))
    ds = config["datasources"][0]
    assert ds["type"] == "prometheus"
    assert ds["url"] == "http://prometheus:9090"
    assert ds["isDefault"] is True


def test_grafana_dashboard_provider_points_at_the_mounted_dashboards_folder(
    compose: dict[str, Any],
):
    """The provider's `path` must resolve inside the ONE `provisioning` bind
    mount the compose service declares — a second bind mount nested inside
    the first's target fails on Docker Desktop (a real bug this test would
    have caught: "read-only file system" creating the nested mountpoint)."""
    config = yaml.safe_load(GRAFANA_DASHBOARD_PROVIDER.read_text(encoding="utf-8"))
    provider = config["providers"][0]
    provisioned_path = provider["options"]["path"]
    assert provisioned_path.startswith("/etc/grafana/provisioning/")

    volumes = compose["services"]["grafana"]["volumes"]
    assert len(volumes) == 1, "a second grafana volume risks nesting inside the first's mountpoint"
    assert volumes[0].endswith(":/etc/grafana/provisioning:ro")

    # the dashboard files must actually live on disk under that one mounted
    # tree, at the exact subpath the provider config names.
    relative = provisioned_path.removeprefix("/etc/grafana/provisioning/")
    assert (GRAFANA_PROVISIONING_ROOT / relative).is_dir()


def test_platform_overview_dashboard_is_valid_and_only_cites_real_metrics():
    """Every PromQL target must reference a metric this platform actually
    emits (inventoried across Phase 15 Unit 1's `sm_common.observability.
    Metrics` and each service's own metrics class) — a dashboard panel
    citing a metric that does not exist would render a permanent gap, not
    a real number (Constitution §3)."""
    dashboard_files = list(GRAFANA_DASHBOARDS_DIR.glob("*.json"))
    assert dashboard_files, "no dashboard JSON files found"

    real_metrics = {
        "sm_http_requests_total", "sm_http_request_duration_seconds_bucket",
        "sm_dependency_up", "sm_consumer_lag", "sm_consumer_dlq_total",
        "sm_db_pool_checked_out", "sm_db_pool_size",
        "sm_neo4j_query_duration_seconds_bucket",
        "sm_graph_commands_applied_total",
        "sm_detection_handle_seconds_bucket", "sm_detection_degraded_total",
        "sm_inference_duration_seconds_bucket",
        "sm_rate_limited_total", "sm_authn_failures_total",
        "sm_authz_denials_total", "sm_audit_write_failures_total",
    }

    for path in dashboard_files:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        assert dashboard["schemaVersion"]
        assert dashboard["panels"]
        for panel in dashboard["panels"]:
            assert panel["gridPos"]
            for target in panel["targets"]:
                expr = target["expr"]
                cited = {m for m in real_metrics if m in expr}
                assert cited, f"panel {panel['title']!r} cites no known real metric: {expr}"


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
