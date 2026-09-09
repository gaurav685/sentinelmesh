from __future__ import annotations

from typing import Any

import pytest
from sm_detection_engine.app import create_app
from sm_detection_engine.deps import Services
from sm_detection_engine.engine import DetectionEngine
from sm_detection_engine.metrics import DetectionMetrics

from sm_common.bus import RecordProcessor
from sm_common.observability import build_metrics

from .conftest import FakeConsumer, FakeInference, FakeProducer, FakeRepo, build_settings


class _FakeDb:
    async def ping(self) -> None: ...
    async def dispose(self) -> None: ...


@pytest.fixture
def app_client() -> Any:
    from fastapi.testclient import TestClient

    base = build_metrics("detection-engine")
    dm = DetectionMetrics(base, "detection-engine")
    producer = FakeProducer()
    settings = build_settings()
    engine = DetectionEngine(
        settings=settings, repository=FakeRepo(), producer=producer,  # type: ignore[arg-type]
        inference=FakeInference(), metrics=dm,  # type: ignore[arg-type]
    )
    processor = RecordProcessor(
        producer=producer, consumer_group="detection", handle=engine.handle,  # type: ignore[arg-type]
        metrics=base, service_name="detection-engine",
    )
    services = Services(
        settings=settings, metrics=base, detection_metrics=dm, db=_FakeDb(),  # type: ignore[arg-type]
        producer=producer, consumer=FakeConsumer(), engine=engine, processor=processor,
    )
    with TestClient(create_app(services=services)) as c:
        yield c


def test_healthz(app_client: Any) -> None:
    assert app_client.get("/healthz").json()["service"] == "detection-engine"


def test_readyz_probes_every_required_dependency(app_client: Any) -> None:
    body = app_client.get("/readyz").json()
    assert {d["name"] for d in body["dependencies"]} == {"postgres", "kafka_producer", "kafka_consumer"}


def test_meta_and_metrics(app_client: Any) -> None:
    assert app_client.get("/api/v1/meta").json()["service"] == "detection-engine"
    assert "sm_detection_events_total" in app_client.get("/metrics").text
