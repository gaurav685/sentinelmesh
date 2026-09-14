from __future__ import annotations

import uuid
from typing import Any

import pytest
from sm_simulation_service.metrics import SimulationMetrics

from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_common.observability import build_metrics
from sm_common.security import mint_internal_token
from sm_contracts import Decoy, DecoyInteraction, DecoyInteractionIn, RegisterDecoyRequest

_TEST_JWT_KEY = "simulation-service-test-signing-key-0123456789abcd"


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "simulation-service",
        "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY,
        "oidc_client_secret": "s",
        "neo4j_password": "x",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


def token(*, audience: str = "simulation-service", key: str = _TEST_JWT_KEY, tenant: Any = None) -> str:
    return mint_internal_token(
        signing_key=key, subject="api-gateway", tenant_id=tenant or uuid.uuid4(), audience=audience,
    )


class FakeDecoyRepo:
    def __init__(self) -> None:
        self.decoys: dict[str, Decoy] = {}
        self.interactions: dict[str, list[DecoyInteraction]] = {}

    async def register(self, tenant_id: uuid.UUID, req: RegisterDecoyRequest) -> Decoy:
        decoy = Decoy(
            id=str(uuid.uuid4()), tenant_id=str(tenant_id), name=req.name, kind=req.kind,
            network_boundary=req.network_boundary, status="active", ttl_seconds=req.ttl_seconds,
            tags=req.tags, created_at=utcnow(),
        )
        self.decoys[decoy.id] = decoy
        self.interactions[decoy.id] = []
        return decoy

    async def get(self, tenant_id: uuid.UUID, decoy_id: uuid.UUID) -> Decoy | None:
        decoy = self.decoys.get(str(decoy_id))
        return decoy if decoy is not None and decoy.tenant_id == str(tenant_id) else None

    async def list_decoys(
        self, tenant_id: uuid.UUID, *, status: str | None = None, limit: int = 200
    ) -> list[Decoy]:
        out = [d for d in self.decoys.values() if d.tenant_id == str(tenant_id)]
        if status:
            out = [d for d in out if d.status == status]
        return out[:limit]

    async def teardown(self, tenant_id: uuid.UUID, decoy_id: uuid.UUID) -> Decoy | None:
        decoy = await self.get(tenant_id, decoy_id)
        if decoy is None:
            return None
        if decoy.status != "torn_down":
            decoy = decoy.model_copy(update={"status": "torn_down", "torn_down_at": utcnow()})
            self.decoys[decoy.id] = decoy
        return decoy

    async def record_interaction(
        self, tenant_id: uuid.UUID, decoy_id: uuid.UUID, interaction: DecoyInteractionIn
    ) -> DecoyInteraction | None:
        decoy = await self.get(tenant_id, decoy_id)
        if decoy is None or decoy.status != "active":
            return None
        out = DecoyInteraction(
            id=str(uuid.uuid4()), decoy_id=decoy.id, tenant_id=decoy.tenant_id, source=interaction.source,
            technique_hint=interaction.technique_hint, detail=interaction.detail, captured_at=utcnow(),
        )
        self.interactions[decoy.id].append(out)
        return out

    async def list_interactions(
        self, tenant_id: uuid.UUID, decoy_id: uuid.UUID, *, limit: int = 200
    ) -> list[DecoyInteraction]:
        return list(self.interactions.get(str(decoy_id), []))[:limit]


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bytes]] = []

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...

    async def send(self, topic: str, *, key: str, value: bytes, headers: Any = None) -> None:
        self.sent.append((topic, key, value))


class _FakeDb:
    async def ping(self) -> None: ...
    async def dispose(self) -> None: ...


@pytest.fixture
def repo() -> FakeDecoyRepo:
    return FakeDecoyRepo()


@pytest.fixture
def producer() -> FakeProducer:
    return FakeProducer()


def _build_client(repo: FakeDecoyRepo, producer: FakeProducer | None) -> Any:
    from fastapi.testclient import TestClient
    from sm_simulation_service.app import create_app
    from sm_simulation_service.deps import Services

    base = build_metrics("simulation-service")
    services = Services(
        settings=build_settings(), metrics=base, sim_metrics=SimulationMetrics(base, "simulation-service"),
        db=_FakeDb(), decoy_repo=repo, producer=producer,  # type: ignore[arg-type]
    )
    c = TestClient(create_app(services=services))
    with c:
        yield c


@pytest.fixture
def client(repo: FakeDecoyRepo, producer: FakeProducer) -> Any:
    yield from _build_client(repo, producer)


@pytest.fixture
def client_no_bus(repo: FakeDecoyRepo) -> Any:
    yield from _build_client(repo, None)
