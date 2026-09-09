from __future__ import annotations

import uuid
from typing import Any

import pytest
from sm_mitre_service.app import create_app
from sm_mitre_service.deps import Services
from sm_mitre_service.mapping import MappingEngine
from sm_mitre_service.metrics import MitreMetrics

from sm_common.bus import RecordProcessor
from sm_common.observability import build_metrics

from .conftest import (
    FakeCatalog,
    FakeConsumer,
    FakeMappingDb,
    FakeProducer,
    build_settings,
    token,
)


class _FakeDb:
    async def ping(self) -> None: ...
    async def dispose(self) -> None: ...


@pytest.fixture
def client() -> Any:
    from fastapi.testclient import TestClient

    base = build_metrics("mitre-service")
    mm = MitreMetrics(base, "mitre-service")
    catalog = FakeCatalog()
    engine = MappingEngine(catalog, FakeMappingDb())  # type: ignore[arg-type]
    producer = FakeProducer()
    processor = RecordProcessor(
        producer=producer, consumer_group="mitre-mapping", handle=engine.map_techniques,  # type: ignore[arg-type]
        metrics=base, service_name="mitre-service",
    )
    services = Services(
        settings=build_settings(), metrics=base, mitre_metrics=mm, db=_FakeDb(),  # type: ignore[arg-type]
        catalog=catalog, mapping=engine, producer=producer,  # type: ignore[arg-type]
        consumer=FakeConsumer(), processor=processor,
    )
    with TestClient(create_app(services=services)) as c:
        yield c


def _auth(**kw: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(**kw)}"}


def test_techniques_requires_a_token(client: Any) -> None:
    assert client.get("/api/v1/mitre/techniques").status_code == 401


def test_techniques_lists_the_catalog(client: Any) -> None:
    r = client.get("/api/v1/mitre/techniques", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["matrix"]["version"] == "test-1"
    assert {t["technique_id"] for t in body["techniques"]} == {"T1110", "T1110.001", "T1021"}


def test_map_validates_against_the_catalog(client: Any) -> None:
    r = client.post(
        "/api/v1/mitre/map",
        json={
            "subject_type": "detection", "subject_id": str(uuid.uuid4()),
            "technique_ids": ["T1110", "T404"], "rationale": "test",
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert [m["technique_id"] for m in body["matches"]] == ["T1110"]
    assert body["unmapped"] == ["T404"]
    assert body["persisted"] == 0


def test_readyz_reports_the_catalog(client: Any) -> None:
    deps = {d["name"]: d for d in client.get("/readyz").json()["dependencies"]}
    assert deps["attack_catalog"]["healthy"] is True
    assert "3 techniques" in deps["attack_catalog"]["detail"]


def test_healthz_and_metrics(client: Any) -> None:
    assert client.get("/healthz").json()["service"] == "mitre-service"
    assert "sm_mitre_detections_total" in client.get("/metrics").text
