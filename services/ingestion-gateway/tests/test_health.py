from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from sm_ingestion_gateway.app import create_app


def test_healthz_is_always_200(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_readyz_200_when_dependencies_are_up(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["ready"] is True


def test_readyz_503_when_postgres_is_down(client: TestClient, rig: Any) -> None:
    rig.db.healthy = False
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["ready"] is False


def test_metrics_endpoint_renders(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "sm_" in r.text


def test_meta_reports_the_service(client: TestClient) -> None:
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    assert r.json()["service"] == "ingestion-gateway"


def test_no_openapi_in_production(rig: Any, settings_builder: Any) -> None:
    rig.services.settings = settings_builder(
        env="production",
        cors_allowed_origins="https://sentinelmesh.example",
        kafka_security_protocol="SASL_SSL",
    )
    app = create_app(services=rig.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/openapi.json").status_code == 404
        assert c.get("/docs").status_code == 404
