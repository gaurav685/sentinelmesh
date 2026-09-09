"""End-to-end: sensor POST -> ingestion-gateway -> Kafka topic.

Needs Postgres (sensor auth), Redis (dedup / limiter) **and** a Kafka broker:

    docker compose -f deploy/docker/docker-compose.yml --profile bus up -d postgres redis redpanda

The gateway app is built in-process with `SM_EVENT_BUS_ENABLED=true`; the test
consumes `telemetry.raw` and `telemetry.raw.dlq` to prove the round trip.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from aiokafka.structs import ConsumerRecord

from sm_common.bus import EventBusProducer
from sm_common.clock import utcnow
from sm_common.db import Database
from sm_common.db.models import Sensor, Tenant
from sm_common.ids import uuid7
from sm_common.security.passwords import hash_password
from sm_contracts.enums import SensorStatus, SensorType, TenantStatus
from sm_ingestion_gateway.app import create_app

from .conftest import integration_settings

pytestmark = pytest.mark.integration

REQUIRE = os.environ.get("SM_REQUIRE_INTEGRATION") == "1"
BOOTSTRAP = os.environ.get("SM_TEST_KAFKA_BOOTSTRAP", "localhost:19092")
SECRET = "bus-it-sensor-secret"


async def _kafka_reachable() -> bool:
    producer = EventBusProducer(bootstrap_servers=BOOTSTRAP, client_id="it-probe")
    try:
        await asyncio.wait_for(producer.start(), timeout=5)
        await asyncio.wait_for(producer.ping(), timeout=5)
        return True
    except (KafkaConnectionError, TimeoutError, OSError):
        return False
    finally:
        await producer.stop()


@pytest_asyncio.fixture
async def kafka_ready() -> None:
    if not await _kafka_reachable():
        msg = (
            f"Kafka/Redpanda not reachable at {BOOTSTRAP}; start it with "
            "`docker compose --profile bus up -d redpanda`"
        )
        if REQUIRE:
            pytest.fail(f"SM_REQUIRE_INTEGRATION=1 but {msg}")
        pytest.skip(msg)


@pytest_asyncio.fixture
async def seeded(clean: Database) -> tuple[str, str]:
    """A tenant + one active sensor. Returns (authorization header value, sensor_id str)."""
    tenant_id = uuid7()
    sensor_id = uuid7()
    async with clean.transaction() as session:
        session.add(
            Tenant(id=tenant_id, slug="bus-it", name="Bus IT",
                   status=TenantStatus.active.value, settings={})
        )
        await session.flush()
        session.add(
            Sensor(id=sensor_id, tenant_id=tenant_id, name="bus-it-sensor",
                   type=SensorType.network.value, status=SensorStatus.active.value,
                   credential_hash=hash_password(SECRET))
        )
    return f"{sensor_id}.{SECRET}", str(sensor_id)


@pytest_asyncio.fixture
async def gateway(kafka_ready: None) -> AsyncIterator[httpx.AsyncClient]:
    settings = integration_settings(
        service_name="ingestion-gateway",
        event_bus_enabled=True,
        kafka_bootstrap_servers=BOOTSTRAP,
        rate_limit_per_minute=200,
    )
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as ac:
            yield ac


async def _drain(
    topic: str, match: Callable[[ConsumerRecord], bool], *, timeout_s: float = 20.0
) -> ConsumerRecord | None:
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=BOOTSTRAP, group_id=f"it-{uuid7()}",
        auto_offset_reset="earliest", enable_auto_commit=False,
    )
    await consumer.start()
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            got = await consumer.getmany(timeout_ms=1000)
            for msgs in got.values():
                for m in msgs:
                    if match(m):
                        return m
        return None
    finally:
        await consumer.stop()


async def test_accepted_event_lands_on_telemetry_raw(
    gateway: httpx.AsyncClient, seeded: tuple[str, str]
) -> None:
    auth, sensor_id = seeded
    body = {"occurred_at": utcnow().isoformat(), "src_ip": "10.9.9.9",
            "dst_ip": "8.8.8.8", "protocol": "tcp", "dst_port": 443}
    r = await gateway.post("/api/v1/ingest/network_flow", json=body,
                           headers={"authorization": auth})
    assert r.status_code == 202
    event_id = r.json()["event_id"]

    def _match(m: ConsumerRecord) -> bool:
        try:
            return json.loads(m.value)["event_id"] == event_id
        except (ValueError, KeyError):
            return False

    msg = await _drain("telemetry.raw", _match)
    assert msg is not None, "accepted event never appeared on telemetry.raw"
    doc = json.loads(msg.value)
    assert doc["tenant_id"] and doc["tenant_id"] != "10.9.9.9"
    assert doc["source"]["type"] == "sensor"
    assert doc["source"]["sensor_id"] == sensor_id
    assert doc["payload"]["src_ip"] == "10.9.9.9"
    assert msg.key.decode() == doc["partition_key"]


async def test_malformed_payload_lands_on_the_dlq(
    gateway: httpx.AsyncClient, seeded: tuple[str, str]
) -> None:
    auth, sensor_id = seeded
    marker = f"it-dlq-{uuid7()}"
    r = await gateway.post(
        "/api/v1/ingest/network_flow",
        json={"occurred_at": utcnow().isoformat(), "src_ip": "not-an-ip",
              "dst_ip": "8.8.8.8", "protocol": "tcp", "src_host": marker},
        headers={"authorization": auth},
    )
    assert r.status_code == 422

    msg = await _drain("telemetry.raw.dlq", lambda m: marker.encode() in m.value)
    assert msg is not None, "rejected body never appeared on telemetry.raw.dlq"
    headers = dict(msg.headers)
    assert headers["reason"] == b"schema_validation"
    assert headers["sensor_id"] == sensor_id.encode()
