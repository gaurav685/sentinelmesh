"""In-memory test rig for the ingestion gateway.

The real app is built — real routing, real middleware, real exception handlers,
the real ingest pipeline. Only the infrastructure is faked: sensor auth resolves
against a small in-memory registry, Redis is a dict, and the sinks record instead
of producing to Kafka. No Docker needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_common.errors import Unauthenticated
from sm_common.ids import uuid7
from sm_common.observability import build_metrics
from sm_common.security import SensorIdentity
from sm_contracts import EventEnvelope, SensorType
from sm_ingestion_gateway.app import create_app
from sm_ingestion_gateway.dedup import Dedup
from sm_ingestion_gateway.deps import Services
from sm_ingestion_gateway.metrics import IngestionMetrics

TENANT_ID = uuid7()
SENSOR_ID = uuid7()
GOOD_CREDENTIAL = f"{SENSOR_ID}.s3cret"


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeRedis:
    def __init__(self) -> None:
        self.healthy = True
        self._store: dict[str, str] = {}

    async def ping(self) -> None:
        if not self.healthy:
            raise ConnectionError("redis down")

    async def incr(self, key: str) -> int:
        if not self.healthy:
            raise ConnectionError("redis down")
        value = int(self._store.get(key, "0")) + 1
        self._store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if not self.healthy:
            raise ConnectionError("redis down")
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def flushdb(self) -> None:
        self._store.clear()

    async def aclose(self) -> None:
        return None


class FakeCache:
    def __init__(self) -> None:
        self.client = FakeRedis()

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        return None


class FakeSession:
    async def close(self) -> None:
        return None


class FakeDatabase:
    def __init__(self) -> None:
        self.healthy = True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[FakeSession]:
        yield FakeSession()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[FakeSession]:
        yield FakeSession()

    async def ping(self) -> None:
        if not self.healthy:
            raise ConnectionError("postgres down")

    async def dispose(self) -> None:
        return None


@dataclass
class FakeSensorRecord:
    identity: SensorIdentity
    secret: str


class FakeSensorAuth:
    """Resolves `<sensor_id>.<secret>` against an in-memory registry."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, FakeSensorRecord] = {}

    def register(self, record: FakeSensorRecord) -> None:
        self._by_id[record.identity.sensor_id] = record

    async def authenticate(
        self, session: Any, *, presented_credential: str
    ) -> SensorIdentity:
        token = presented_credential.removeprefix("Bearer ").strip()
        raw_id, _, secret = token.partition(".")
        try:
            sensor_id = UUID(raw_id)
        except ValueError:
            raise Unauthenticated() from None
        record = self._by_id.get(sensor_id)
        if record is None or secret != record.secret:
            raise Unauthenticated()
        return record.identity


class RecordingRawSink:
    def __init__(self) -> None:
        self.events: list[EventEnvelope[Any]] = []
        self.fail = False

    async def put(self, envelope: EventEnvelope[Any]) -> None:
        if self.fail:
            raise ConnectionError("event bus down")
        self.events.append(envelope)


class RecordingDeadLetterSink:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.fail = False

    async def put(
        self, *, source_type: str, raw_body: bytes, reason: str, sensor_id: UUID | None
    ) -> None:
        if self.fail:
            raise ConnectionError("dlq down")
        self.items.append(
            {"source_type": source_type, "raw_body": raw_body, "reason": reason,
             "sensor_id": sensor_id}
        )


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "ingestion-gateway",
        "pg_password": "x",
        "internal_jwt_signing_key": "k",
        "oidc_client_secret": "s",
        "rate_limit_per_minute": 5,
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


@dataclass
class Rig:
    services: Services
    raw: RecordingRawSink
    dlq: RecordingDeadLetterSink
    cache: FakeCache
    db: FakeDatabase
    sensor_auth: FakeSensorAuth
    identity: SensorIdentity
    settings_over: dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def rig() -> Rig:
    settings = build_settings()
    db = FakeDatabase()
    cache = FakeCache()
    base_metrics = build_metrics("ingestion-gateway")
    raw = RecordingRawSink()
    dlq = RecordingDeadLetterSink()
    sensor_auth = FakeSensorAuth()

    identity = SensorIdentity(sensor_id=SENSOR_ID, tenant_id=TENANT_ID, type=SensorType.network)
    sensor_auth.register(FakeSensorRecord(identity=identity, secret="s3cret"))

    services = Services(
        settings=settings,
        db=db,  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        metrics=base_metrics,
        ingest_metrics=IngestionMetrics(base_metrics, "ingestion-gateway"),
        sensor_auth=sensor_auth,  # type: ignore[arg-type]
        raw_sink=raw,
        dlq_sink=dlq,
        dedup=Dedup(cache.client, ttl_seconds=900),  # type: ignore[arg-type]
    )
    return Rig(services=services, raw=raw, dlq=dlq, cache=cache, db=db,
               sensor_auth=sensor_auth, identity=identity)


@pytest.fixture
def client(rig: Rig) -> AsyncIterator[TestClient]:
    app = create_app(services=rig.services)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth_header() -> dict[str, str]:
    return {"authorization": GOOD_CREDENTIAL}


@pytest.fixture
def sensor_id() -> UUID:
    return SENSOR_ID


@pytest.fixture
def tenant_id() -> UUID:
    return TENANT_ID


@pytest.fixture
def good_credential() -> str:
    return GOOD_CREDENTIAL


@pytest.fixture
def settings_builder() -> Any:
    return build_settings


def _recent_iso() -> str:
    """A timestamp a second in the past — inside the envelope's 5-minute skew
    guard, which is anchored on the real wall clock."""
    return (utcnow() - timedelta(seconds=1)).isoformat()


@pytest.fixture
def now_iso() -> str:
    return _recent_iso()


@pytest.fixture
def flow() -> Any:
    def _flow(**over: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "occurred_at": _recent_iso(), "src_ip": "10.0.0.1", "dst_ip": "93.184.216.34",
            "protocol": "TCP", "dst_port": 443,
        }
        body.update(over)
        return body

    return _flow
