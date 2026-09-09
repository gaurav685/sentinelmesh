from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sm_ti_service.metrics import TiMetrics

from sm_common.config import AppSettings
from sm_common.observability import build_metrics
from sm_common.security import mint_internal_token
from sm_contracts import (
    EnrichmentMatch,
    IndicatorFreshness,
    IndicatorType,
    Provenance,
    ThreatIndicator,
    TiConfidence,
    TiSourceKind,
    TiUpdateAction,
)

_TEST_JWT_KEY = "threat-intel-service-test-signing-key-0123456789"
_NOW = datetime.now(UTC)


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "threat-intel-service", "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY, "oidc_client_secret": "s",
        "neo4j_password": "x",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


def token(*, audience: str = "threat-intel-service", key: str = _TEST_JWT_KEY, tenant: Any = None) -> str:
    return mint_internal_token(
        signing_key=key, subject="analyst-1", tenant_id=tenant or uuid.uuid4(), audience=audience,
    )


def indicator(*, value: str = "9.9.9.9", matched: bool = True) -> ThreatIndicator:
    return ThreatIndicator(
        id=uuid.uuid4(), created_at=_NOW, updated_at=_NOW, type=IndicatorType.ipv4, value=value,
        tenant_id=None, source="fixture:demo", confidence=TiConfidence.high, reputation=0.9,
        first_seen=_NOW, last_seen=_NOW, expires_at=None, freshness=IndicatorFreshness.fresh,
        tags=["c2"], actor_id=None,
        provenance=Provenance(provider="fixture:demo", source_kind=TiSourceKind.fixture, retrieved_at=_NOW),
    )


class FakeRepo:
    def __init__(self) -> None:
        self.submitted: list[Any] = []
        self.store: dict[str, ThreatIndicator] = {}

    async def upsert(self, inp: Any) -> tuple[ThreatIndicator, TiUpdateAction]:
        if inp.value == "not-an-ip":
            raise ValueError("bad ipv4")
        self.submitted.append(inp)
        ind = indicator(value=inp.value)
        self.store[inp.value] = ind
        return ind, TiUpdateAction.added

    async def enrich(self, tenant_id: uuid.UUID, items: list[tuple[IndicatorType, str]]) -> list[EnrichmentMatch]:
        out = []
        for itype, value in items:
            hit = value in self.store
            out.append(EnrichmentMatch(
                type=itype, value=value, matched=hit,
                indicator=self.store.get(value), freshness=IndicatorFreshness.fresh if hit else None,
            ))
        return out

    async def list_indicators(self, tenant_id: uuid.UUID, **kw: Any) -> list[ThreatIndicator]:
        return list(self.store.values())


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...

    async def send(self, topic: str, *, key: str, value: bytes, headers: Any = None) -> None:
        self.sent.append((topic, value))


class _FakeDb:
    async def ping(self) -> None: ...
    async def dispose(self) -> None: ...


class _FakeSweeper:
    def stop(self) -> None: ...
    async def run(self) -> None: ...


@pytest.fixture
def client() -> Any:
    from fastapi.testclient import TestClient
    from sm_ti_service.app import create_app
    from sm_ti_service.deps import Services

    base = build_metrics("threat-intel-service")
    repo = FakeRepo()
    producer = FakeProducer()
    services = Services(
        settings=build_settings(), metrics=base, ti_metrics=TiMetrics(base, "threat-intel-service"),
        db=_FakeDb(), repo=repo, producer=producer, sweeper=_FakeSweeper(),  # type: ignore[arg-type]
    )
    c = TestClient(create_app(services=services))
    with c:
        c.fake_repo = repo  # type: ignore[attr-defined]
        c.fake_producer = producer  # type: ignore[attr-defined]
        yield c
