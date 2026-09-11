from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sm_memory_service.metrics import MemoryMetrics

from sm_common.config import AppSettings
from sm_common.observability import build_metrics
from sm_common.security import mint_internal_token
from sm_contracts import AdversaryFingerprint, Campaign, SimilarityMatch, ThreatMemory

_TEST_JWT_KEY = "memory-service-test-signing-key-0123456789abcd"
_NOW = datetime.now(UTC)


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "memory-service",
        "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY,
        "oidc_client_secret": "s",
        "neo4j_password": "x",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


def token(*, audience: str = "memory-service", key: str = _TEST_JWT_KEY, tenant: Any = None) -> str:
    return mint_internal_token(
        signing_key=key, subject="api-gateway", tenant_id=tenant or uuid.uuid4(), audience=audience,
    )


def pattern(tenant_id: Any, **over: Any) -> ThreatMemory:
    base: dict[str, Any] = dict(
        id=uuid.uuid4(), tenant_id=tenant_id, subject_type="host", subject_id="web01",
        pattern_kind="technique_sequence", technique_ids=["T1110"], occurrence_count=1,
        first_seen=_NOW, last_seen=_NOW, source="attack_chain:c1", created_at=_NOW, updated_at=_NOW,
    )
    base.update(over)
    return ThreatMemory(**base)


def campaign(tenant_id: Any, **over: Any) -> Campaign:
    base: dict[str, Any] = dict(
        id=uuid.uuid4(), tenant_id=tenant_id, status="active", chain_ids=["c1"],
        technique_ids=["T1110"], first_seen=_NOW, last_seen=_NOW, created_at=_NOW, updated_at=_NOW,
    )
    base.update(over)
    return Campaign(**base)


def fingerprint(tenant_id: Any, **over: Any) -> AdversaryFingerprint:
    base: dict[str, Any] = dict(
        id=uuid.uuid4(), tenant_id=tenant_id, subject_type="identity", subject_id="svc-backup",
        technique_ids=["T1110"], campaign_ids=["c1"], first_seen=_NOW, last_seen=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    base.update(over)
    return AdversaryFingerprint(**base)


class FakeMemoryRepo:
    def __init__(self) -> None:
        self.similar_response: list[SimilarityMatch] = []
        self.patterns_response: list[ThreatMemory] = []
        self.fingerprint_response: AdversaryFingerprint | None = None
        self.campaigns_response: list[Campaign] = []
        self.campaign_response: Campaign | None = None
        self.calls: list[tuple[str, Any]] = []

    async def find_similar(self, tenant_id: Any, *, kind: str, technique_ids: Any, limit: int = 10) -> Any:
        self.calls.append(("find_similar", tenant_id))
        return self.similar_response

    async def list_patterns(self, tenant_id: Any, *, subject_type: Any = None, subject_id: Any = None) -> Any:
        self.calls.append(("list_patterns", tenant_id))
        return self.patterns_response

    async def get_fingerprint(self, tenant_id: Any, *, subject_type: Any, subject_id: Any) -> Any:
        self.calls.append(("get_fingerprint", tenant_id))
        return self.fingerprint_response

    async def list_campaigns(self, tenant_id: Any, *, status: Any = None) -> Any:
        self.calls.append(("list_campaigns", tenant_id))
        return self.campaigns_response

    async def get_campaign(self, tenant_id: Any, campaign_id: Any) -> Any:
        self.calls.append(("get_campaign", tenant_id))
        return self.campaign_response


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


class _FakeConsumer:
    group_id = "memory"

    async def ping(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    def request_stop(self) -> None: ...

    async def run(self, processor: Any) -> None: ...


class _FakeProcessor:
    pass


class _FakeSweeper:
    def stop(self) -> None: ...
    async def run(self) -> None: ...


@pytest.fixture
def repo() -> FakeMemoryRepo:
    return FakeMemoryRepo()


@pytest.fixture
def producer() -> FakeProducer:
    return FakeProducer()


@pytest.fixture
def client(repo: FakeMemoryRepo, producer: FakeProducer) -> Any:
    from fastapi.testclient import TestClient
    from sm_memory_service.app import create_app
    from sm_memory_service.deps import Services

    base = build_metrics("memory-service")
    services = Services(
        settings=build_settings(), metrics=base, mem_metrics=MemoryMetrics(base, "memory-service"),
        db=_FakeDb(), repo=repo,  # type: ignore[arg-type]
        http=None, chains=None,  # type: ignore[arg-type]
        producer=producer, consumer=_FakeConsumer(), processor=_FakeProcessor(),  # type: ignore[arg-type]
        sweeper=_FakeSweeper(),  # type: ignore[arg-type]
    )
    c = TestClient(create_app(services=services))
    with c:
        yield c
