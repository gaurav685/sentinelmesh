from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiokafka.structs import ConsumerRecord
from sm_correlation_engine.metrics import CorrelationMetrics

from sm_common.config import AppSettings
from sm_common.observability import build_metrics
from sm_common.security import mint_internal_token
from sm_contracts import (
    AttackChainModel,
    AttackChainPayload,
    AttackStage,
    ChainStatus,
    DetectionPayload,
    EntityRef,
    EventEnvelope,
    EventSource,
    EventType,
    ScoringStatus,
    Severity,
    SourceType,
    ThreatSubjectType,
    make_partition_key,
)

_TEST_JWT_KEY = "correlation-engine-test-signing-key-0123456789"
TENANT_ID = uuid.uuid4()
_BASE = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "correlation-engine", "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY, "oidc_client_secret": "s", "neo4j_password": "x",
        "kafka_consumer_group": "correlation",
        "chain_window_seconds": 86_400, "chain_dormant_seconds": 21_600,
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


def token(*, audience: str = "correlation-engine", key: str = _TEST_JWT_KEY, tenant: Any = None) -> str:
    return mint_internal_token(
        signing_key=key, subject="analyst-1", tenant_id=tenant or TENANT_ID, audience=audience,
    )


def detection_payload(
    *,
    detection_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    technique_ids: list[str] | None = None,
    severity: Severity = Severity.medium,
    score: float = 0.6,
    rule_id: str | None = "rule.auth.failed_burst",
    subject: tuple[ThreatSubjectType, str] | None = (ThreatSubjectType.identity, "alice"),
    occurred_offset_s: int = 0,
    scoring_status: ScoringStatus = ScoringStatus.ok,
) -> DetectionPayload:
    occurred = _BASE + timedelta(seconds=occurred_offset_s)
    st, sid = subject if subject else (None, None)
    return DetectionPayload(
        detection_id=detection_id or uuid.uuid4(),
        tenant_id=tenant_id or TENANT_ID,
        occurred_at=occurred, detected_at=occurred, detector="composite", rule_id=rule_id,
        title="t", severity=severity, score=score, scoring_status=scoring_status,
        raw_event_id=uuid.uuid4(),
        subject_type=st, subject_id=sid,
        entities=[EntityRef(kind="identity", value="alice")],
        technique_ids=technique_ids or [], evidence_count=2, dedup_key="k",
    )


def envelope_for(payload: DetectionPayload) -> EventEnvelope[DetectionPayload]:
    return EventEnvelope[DetectionPayload](
        event_id=payload.detection_id, event_type=EventType.detection_raised, event_version=1,
        occurred_at=payload.occurred_at, ingested_at=payload.occurred_at,
        producer="detection-engine@0.1.0", tenant_id=payload.tenant_id,
        source=EventSource(type=SourceType.sensor, sensor_id=uuid.uuid4()),
        correlation_id=uuid.uuid4(),
        partition_key=make_partition_key(payload.tenant_id, str(payload.detection_id)),
        payload=payload, metadata={},
    )


def record_for(payload: DetectionPayload) -> ConsumerRecord:
    value = envelope_for(payload).model_dump_json().encode("utf-8")
    return ConsumerRecord(
        topic="detections", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=value, checksum=None, serialized_key_size=0,
        serialized_value_size=len(value), headers=(),
    )


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []
        self.fail = False

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...

    async def send(self, topic: str, *, key: str, value: bytes, headers: Any = None) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.sent.append((topic, value))

    def chains(self) -> list[AttackChainPayload]:
        import json
        return [
            AttackChainPayload.model_validate(json.loads(v)["payload"])
            for t, v in self.sent if t == "attack_chains"
        ]


def _chain_model(**over: Any) -> AttackChainModel:
    now = _BASE
    base: dict[str, Any] = dict(
        id=uuid.uuid4(), tenant_id=TENANT_ID, created_at=now, updated_at=now,
        subject_type=ThreatSubjectType.identity, subject_id="alice", status=ChainStatus.active,
        window_start=now, first_seen=now, last_seen=now, stages=[], distinct_stage_count=2,
        progression=0.5, confidence=0.6, score=0.55, score_version="v1", scoring_status="ok",
        technique_ids=["T1110"], detection_count=3, notes=[],
    )
    base.update(over)
    return AttackChainModel(**base)


class FakeChainRepo:
    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.store: dict[str, AttackChainModel] = {}
        self.fail = False

    async def correlate(self, staged: Any, *, tenant_id: Any, subject_type: Any, subject_id: str,
                        now: Any = None) -> Any:
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((staged, subject_type, subject_id))
        model = _chain_model(subject_type=subject_type, subject_id=subject_id, tenant_id=tenant_id)
        self.store[str(model.id)] = model
        from sm_correlation_engine.chains import ChainUpdate

        payload = AttackChainPayload(
            chain_id=model.id, tenant_id=model.tenant_id, subject_type=model.subject_type,
            subject_id=model.subject_id, status=model.status, first_seen=model.first_seen,
            last_seen=model.last_seen, updated_at=model.updated_at, stage_count=0,
            distinct_stage_count=model.distinct_stage_count, latest_stage=AttackStage.credential_access,
            progression=model.progression, confidence=model.confidence, score=model.score,
            score_version=model.score_version, scoring_status=model.scoring_status,
            technique_ids=model.technique_ids, detection_count=model.detection_count,
        )
        return ChainUpdate(chain=model, payload=payload, created=True, new_detection=True)

    async def get_chain(self, tenant_id: Any, chain_id: Any) -> AttackChainModel | None:
        m = self.store.get(str(chain_id))
        if m is None or str(m.tenant_id) != str(tenant_id):
            return None
        return m

    async def list_chains(self, tenant_id: Any, **kw: Any) -> list[AttackChainModel]:
        return [m for m in self.store.values() if str(m.tenant_id) == str(tenant_id)]


class _FakeDb:
    async def ping(self) -> None: ...
    async def dispose(self) -> None: ...


class _FakeConsumer:
    group_id = "correlation"

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...
    async def run(self, handler: Any) -> None: ...


@pytest.fixture
def metrics() -> CorrelationMetrics:
    return CorrelationMetrics(build_metrics("correlation-engine"), "correlation-engine")


@pytest.fixture
def client() -> Any:
    from fastapi.testclient import TestClient
    from sm_correlation_engine.app import create_app
    from sm_correlation_engine.deps import Services

    base = build_metrics("correlation-engine")
    repo = FakeChainRepo()
    services = Services(
        settings=build_settings(), metrics=base,
        correlation_metrics=CorrelationMetrics(base, "correlation-engine"),
        db=_FakeDb(), repo=repo, producer=FakeProducer(),  # type: ignore[arg-type]
        consumer=_FakeConsumer(), processor=None,  # type: ignore[arg-type]
    )
    c = TestClient(create_app(services=services))
    with c:
        c.fake_repo = repo  # type: ignore[attr-defined]
        yield c
