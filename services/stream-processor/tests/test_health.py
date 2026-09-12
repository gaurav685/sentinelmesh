from __future__ import annotations

from typing import Any


def test_healthz(app_client: Any) -> None:
    assert app_client.get("/healthz").status_code == 200


def test_readyz(app_client: Any) -> None:
    r = app_client.get("/readyz")
    assert r.status_code == 200
    assert {d["name"] for d in r.json()["dependencies"]} == {"kafka_producer", "kafka_consumer"}


def test_health_deps(app_client: Any) -> None:
    r = app_client.get("/health/deps")
    assert r.status_code == 200
    assert {d["name"] for d in r.json()["dependencies"]} == {"kafka_producer", "kafka_consumer"}


def test_meta_and_metrics(app_client: Any) -> None:
    assert app_client.get("/api/v1/meta").json()["service"] == "stream-processor"
    assert app_client.get("/metrics").status_code == 200
