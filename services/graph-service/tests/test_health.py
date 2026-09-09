from __future__ import annotations

from typing import Any


def test_healthz_is_liveness_only(app_client: Any) -> None:
    r = app_client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "graph-service"


def test_readyz_reports_every_dependency(app_client: Any) -> None:
    r = app_client.get("/readyz")
    assert r.status_code == 200
    names = {d["name"] for d in r.json()["dependencies"]}
    assert names == {"kafka_producer", "kafka_consumer", "neo4j"}


def test_meta_route(app_client: Any) -> None:
    r = app_client.get("/api/v1/meta")
    assert r.status_code == 200
    assert r.json()["service"] == "graph-service"


def test_metrics_endpoint(app_client: Any) -> None:
    r = app_client.get("/metrics")
    assert r.status_code == 200
    assert "sm_graph_commands_applied_total" in r.text
