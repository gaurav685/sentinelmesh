from __future__ import annotations

from typing import Any


def test_healthz_ok(app_client: Any) -> None:
    assert app_client.get("/healthz").status_code == 200


def test_readyz_ok_when_broker_reachable(app_client: Any) -> None:
    r = app_client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["ready"] is True
    names = {d["name"] for d in r.json()["dependencies"]}
    assert names == {"kafka_producer", "kafka_consumer"}


def test_readyz_503_when_producer_down(app_client: Any) -> None:
    app_client.app.state.services.producer.fail = True
    r = app_client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["ready"] is False


def test_meta_and_metrics(app_client: Any) -> None:
    assert app_client.get("/api/v1/meta").json()["service"] == "normalization-engine"
    m = app_client.get("/metrics")
    assert m.status_code == 200
    assert "sm_normalize_" in m.text or "sm_" in m.text
