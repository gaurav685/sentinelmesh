from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sm_mitre_service.engine import MappingHandler
from sm_mitre_service.mapping import MappingEngine
from sm_mitre_service.metrics import MitreMetrics

from sm_common.config import AppSettings
from sm_common.observability import build_metrics
from sm_common.security import mint_internal_token
from sm_contracts import (
    AttackMatrixVersion,
    AttackTechnique,
    DetectionPayload,
    DetectorKind,
    EventEnvelope,
    EventSource,
    EventType,
    ScoringStatus,
    Severity,
    SourceType,
    make_partition_key,
)

_TEST_JWT_KEY = "mitre-service-test-signing-key-0123456789"
FIXTURE_BUNDLE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "attack_mini_bundle.json"

_TECHNIQUES: dict[str, AttackTechnique] = {
    "T1110": AttackTechnique(
        technique_id="T1110", name="Brute Force", tactic_ids=["TA0006"], matrix_version="test-1",
    ),
    "T1110.001": AttackTechnique(
        technique_id="T1110.001", name="Password Guessing", tactic_ids=["TA0006"],
        is_subtechnique=True, parent_technique_id="T1110", matrix_version="test-1",
    ),
    "T1021": AttackTechnique(
        technique_id="T1021", name="Remote Services", tactic_ids=["TA0008"], matrix_version="test-1",
    ),
    "T9999": AttackTechnique(
        technique_id="T9999", name="Deprecated Example", tactic_ids=["TA0006"],
        matrix_version="test-1", deprecated=True,
    ),
}
_TACTICS = {"TA0006": "Credential Access", "TA0008": "Lateral Movement"}


class FakeCatalog:
    def __init__(self, *, imported: bool = True) -> None:
        self._imported = imported

    async def latest_version(self) -> AttackMatrixVersion | None:
        if not self._imported:
            return None
        return AttackMatrixVersion(
            version="test-1", source="fixture", imported_at=datetime.now(UTC),
            tactic_count=2, technique_count=3, subtechnique_count=1,
            stix_bundle_sha256="0" * 64,
        )

    async def tactic_names(self) -> dict[str, str]:
        return dict(_TACTICS)

    async def get_technique(self, technique_id: str) -> AttackTechnique | None:
        return _TECHNIQUES.get(technique_id)

    async def technique_count(self) -> int:
        return 3 if self._imported else 0

    async def list_techniques(self, *, include_deprecated: bool = False) -> list[AttackTechnique]:
        return [t for t in _TECHNIQUES.values() if include_deprecated or not t.deprecated]


class FakeMappingDb:
    def __init__(self) -> None:
        self.executed: list[Any] = []

    def transaction(self) -> Any:
        db = self

        class _Ctx:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

            async def execute(self, stmt: Any, *a: object) -> Any:
                db.executed.append(stmt)
                return None

        return _Ctx()


class FakeProducer:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...
    async def send(self, *a: object, **kw: object) -> None: ...


class FakeConsumer:
    group_id = "mitre-mapping"

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...
    async def run(self, handler: Any) -> None: ...


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "mitre-service", "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY, "oidc_client_secret": "s",
        "neo4j_password": "x", "kafka_consumer_group": "mitre-mapping",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


def token(*, audience: str = "mitre-service", key: str = _TEST_JWT_KEY, tenant: Any = None) -> str:
    return mint_internal_token(
        signing_key=key, subject="detection-engine",
        tenant_id=tenant or uuid.uuid4(), audience=audience,
    )


def detection_payload(*, technique_ids: list[str], tenant: uuid.UUID | None = None) -> DetectionPayload:
    return DetectionPayload(
        detection_id=uuid.uuid4(), tenant_id=tenant or uuid.uuid4(),
        occurred_at=datetime.now(UTC), detected_at=datetime.now(UTC),
        detector=DetectorKind.rule, rule_id="rule.auth.failed_burst",
        title="t", severity=Severity.medium, score=0.6, scoring_status=ScoringStatus.ok,
        entities=[], technique_ids=technique_ids, evidence_count=1, dedup_key="k",
    )


def detection_record(payload: DetectionPayload) -> Any:
    from aiokafka.structs import ConsumerRecord

    env = EventEnvelope[DetectionPayload](
        event_id=payload.detection_id, event_type=EventType.detection_raised, event_version=1,
        occurred_at=payload.occurred_at, ingested_at=datetime.now(UTC),
        producer="detection-engine@0.1.0", tenant_id=payload.tenant_id,
        source=EventSource(type=SourceType.sensor, sensor_id=uuid.uuid4()),
        correlation_id=uuid.uuid4(),
        partition_key=make_partition_key(payload.tenant_id, str(payload.detection_id)),
        payload=payload, metadata={},
    )
    v = env.model_dump_json().encode()
    return ConsumerRecord(
        topic="detections", partition=0, offset=0, timestamp=0, timestamp_type=0,
        key=b"k", value=v, checksum=None, serialized_key_size=0,
        serialized_value_size=len(v), headers=(),
    )


@pytest.fixture
def mapping_engine() -> tuple[MappingEngine, FakeMappingDb]:
    db = FakeMappingDb()
    return MappingEngine(FakeCatalog(), db), db  # type: ignore[arg-type]


@pytest.fixture
def handler(mapping_engine: tuple[MappingEngine, FakeMappingDb]) -> tuple[MappingHandler, FakeMappingDb]:
    engine, db = mapping_engine
    base = build_metrics("mitre-service")
    return MappingHandler(engine=engine, metrics=MitreMetrics(base, "mitre-service")), db
