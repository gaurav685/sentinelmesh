from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from aiokafka.structs import ConsumerRecord
from sm_memory_service.ingest import MemoryIngestHandler
from sm_memory_service.metrics import MemoryMetrics

from sm_common.bus import PoisonError, TransientError
from sm_common.errors import DependencyUnavailable
from sm_common.observability import build_metrics
from sm_contracts import (
    AttackChainModel,
    AttackChainPayload,
    AttackStage,
    Campaign,
    EventEnvelope,
    EventSource,
    EventType,
    SourceType,
    make_partition_key,
)

from .conftest import FakeProducer, campaign

_NOW = datetime.now(UTC)
_TENANT = uuid.uuid4()
_CHAIN_ID = uuid.uuid4()


def _chain_payload() -> AttackChainPayload:
    return AttackChainPayload(
        chain_id=_CHAIN_ID, tenant_id=_TENANT, subject_type="host", subject_id="web01",
        status="active", first_seen=_NOW, last_seen=_NOW, updated_at=_NOW, stage_count=1,
        distinct_stage_count=1, latest_stage=AttackStage.initial_access, progression=0.2,
        confidence=0.5, score=0.4, score_version="v1", scoring_status="ok", detection_count=1,
    )


def _envelope(payload: AttackChainPayload) -> EventEnvelope[AttackChainPayload]:
    return EventEnvelope[AttackChainPayload](
        event_id=uuid.uuid4(), event_type=EventType.attack_chain_updated, event_version=1,
        occurred_at=_NOW, ingested_at=_NOW, producer="correlation-engine@0.1.0",
        tenant_id=payload.tenant_id, source=EventSource(type=SourceType.internal),
        correlation_id=uuid.uuid4(),
        partition_key=make_partition_key(str(payload.tenant_id), payload.subject_id),
        payload=payload, metadata={},
    )


def _record(envelope: EventEnvelope[AttackChainPayload]) -> ConsumerRecord:
    value = envelope.model_dump_json().encode("utf-8")
    return ConsumerRecord(
        topic="attack_chains", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=value, checksum=None, serialized_key_size=0,
        serialized_value_size=len(value), headers=(),
    )


def _full_chain(*, technique_ids: list[str]) -> AttackChainModel:
    return AttackChainModel(
        id=_CHAIN_ID, tenant_id=_TENANT, subject_type="host", subject_id="web01", status="active",
        window_start=_NOW, first_seen=_NOW, last_seen=_NOW, created_at=_NOW, updated_at=_NOW,
        stages=[], distinct_stage_count=1, progression=0.2, confidence=0.5, score=0.4,
        score_version="v1", scoring_status="ok", technique_ids=technique_ids, detection_count=1,
    )


class FakeChainsClient:
    def __init__(self, chain: AttackChainModel | None = None, *, error: Exception | None = None) -> None:
        self.chain = chain
        self.error = error
        self.calls: list[tuple[Any, Any]] = []

    async def get_chain(self, tenant_id: Any, chain_id: Any) -> AttackChainModel | None:
        self.calls.append((tenant_id, chain_id))
        if self.error is not None:
            raise self.error
        return self.chain


class FakeMemoryRepo:
    def __init__(self, campaign_result: Campaign | None = None) -> None:
        self.upserted_patterns: list[dict[str, Any]] = []
        self.upserted_fingerprints: list[dict[str, Any]] = []
        self.campaign_result = campaign_result or campaign(_TENANT)

    async def upsert_pattern(self, tenant_id: Any, **kw: Any) -> Any:
        self.upserted_patterns.append({"tenant_id": tenant_id, **kw})
        return None

    async def attach_chain_to_campaign(self, tenant_id: Any, **kw: Any) -> Campaign:
        return self.campaign_result

    async def upsert_fingerprint(self, tenant_id: Any, **kw: Any) -> Any:
        self.upserted_fingerprints.append({"tenant_id": tenant_id, **kw})
        return None


def _handler(repo: Any, chains: Any, producer: Any) -> MemoryIngestHandler:
    metrics = MemoryMetrics(build_metrics("memory-service-test"), "memory-service")
    return MemoryIngestHandler(repo=repo, chains=chains, producer=producer, metrics=metrics)


async def test_a_chain_update_upserts_a_pattern_and_fingerprint_and_emits_campaign_update() -> None:
    repo = FakeMemoryRepo()
    chains = FakeChainsClient(_full_chain(technique_ids=["T1110", "T1078"]))
    producer = FakeProducer()
    handler = _handler(repo, chains, producer)

    await handler.handle(_record(_envelope(_chain_payload())))

    assert repo.upserted_patterns
    assert repo.upserted_patterns[0]["technique_ids"] == ["T1078", "T1110"]
    assert repo.upserted_fingerprints
    assert len(producer.sent) == 1
    assert producer.sent[0][0] == "campaign.updates"


async def test_a_chain_with_no_techniques_is_skipped() -> None:
    repo = FakeMemoryRepo()
    chains = FakeChainsClient(_full_chain(technique_ids=[]))
    producer = FakeProducer()
    handler = _handler(repo, chains, producer)

    await handler.handle(_record(_envelope(_chain_payload())))

    assert not repo.upserted_patterns
    assert not producer.sent


async def test_a_missing_chain_is_skipped_not_an_error() -> None:
    repo = FakeMemoryRepo()
    chains = FakeChainsClient(None)
    producer = FakeProducer()
    handler = _handler(repo, chains, producer)

    await handler.handle(_record(_envelope(_chain_payload())))

    assert not repo.upserted_patterns


async def test_a_malformed_envelope_is_poison() -> None:
    handler = _handler(FakeMemoryRepo(), FakeChainsClient(), FakeProducer())
    bad = ConsumerRecord(
        topic="attack_chains", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=b"not json", checksum=None, serialized_key_size=0,
        serialized_value_size=8, headers=(),
    )
    with pytest.raises(PoisonError):
        await handler.handle(bad)


async def test_a_dependency_failure_is_transient_not_swallowed() -> None:
    chains = FakeChainsClient(error=DependencyUnavailable("correlation-engine unreachable"))
    handler = _handler(FakeMemoryRepo(), chains, FakeProducer())
    with pytest.raises(TransientError):
        await handler.handle(_record(_envelope(_chain_payload())))
