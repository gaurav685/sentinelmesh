from __future__ import annotations

from typing import Any


def test_healthz(client: Any) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "memory-service"


def test_readyz_reports_every_required_dependency(client: Any) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    assert {d["name"] for d in r.json()["dependencies"]} == {
        "postgres", "kafka_consumer", "kafka_producer",
    }


def test_health_deps_reports_the_same_dependencies(client: Any) -> None:
    r = client.get("/health/deps")
    assert r.status_code == 200
    assert {d["name"] for d in r.json()["dependencies"]} == {
        "postgres", "kafka_consumer", "kafka_producer",
    }


def test_meta_and_metrics(client: Any) -> None:
    assert client.get("/api/v1/meta").json()["service"] == "memory-service"
    assert client.get("/metrics").status_code == 200
