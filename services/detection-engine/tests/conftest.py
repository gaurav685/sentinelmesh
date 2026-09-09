from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiokafka.structs import ConsumerRecord
from sm_detection_engine.engine import DetectionEngine
from sm_detection_engine.metrics import DetectionMetrics
from sm_detection_engine.windows import EventTimeline, FeatureWindows

from sm_common.config import AppSettings
from sm_common.observability import build_metrics
from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EntityRef,
    EventEnvelope,
    EventSource,
    EventType,
    SourceType,
    make_partition_key,
)
from sm_ml import extract_features
from sm_ml.models import AnomalyScore

TENANT_ID = uuid.uuid4()

_RAW_TYPE = {
    CanonicalKind.auth: EventType.telemetry_auth_event,
    CanonicalKind.network_flow: EventType.telemetry_network_flow,
    CanonicalKind.dns: EventType.telemetry_dns_query,
    CanonicalKind.process_exec: EventType.telemetry_process_exec,
    CanonicalKind.file_access: EventType.telemetry_file_access,
}


def canonical(
    kind: CanonicalKind,
    *,
    action: str = "did",
    outcome: str | None = None,
    actor: tuple[str, str] | None = None,
    target: tuple[str, str] | None = None,
    attributes: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    tenant_id: uuid.UUID | None = None,
) -> EventEnvelope[CanonicalEventPayload]:
    a = EntityRef(kind=actor[0], value=actor[1]) if actor else None
    t = EntityRef(kind=target[0], value=target[1]) if target else None
    occurred = occurred_at or datetime.now(UTC) - timedelta(seconds=1)
    raw_id = uuid.uuid4()
    payload = CanonicalEventPayload(
        kind=kind, occurred_at=occurred, action=action, outcome=outcome,
        actor=a, target=t, entities=[r for r in (a, t) if r is not None],
        raw_event_id=raw_id, raw_event_type=_RAW_TYPE[kind], attributes=attributes or {},
        enrichment=enrichment or {},
    )
    tid = tenant_id or TENANT_ID
    return EventEnvelope[CanonicalEventPayload](
        event_id=uuid.uuid4(), event_type=EventType.event_canonical, event_version=1,
        occurred_at=occurred, ingested_at=datetime.now(UTC), producer="normalization-engine@0.1.0",
        tenant_id=tid, source=EventSource(type=SourceType.sensor, sensor_id=uuid.uuid4()),
        correlation_id=uuid.uuid4(),
        partition_key=make_partition_key(tid, a.value if a else "x"),
        payload=payload, metadata={"raw_event_id": str(raw_id)},
    )


def record_for(envelope: EventEnvelope[CanonicalEventPayload]) -> ConsumerRecord:
    value = envelope.model_dump_json().encode("utf-8")
    return ConsumerRecord(
        topic="events.canonical", partition=0, offset=0, timestamp=0, timestamp_type=0,
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

    def detections(self) -> list[dict[str, Any]]:
        return [json.loads(v) for t, v in self.sent if t == "detections"]


@dataclass
class FakeRepo:
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    detections: list[dict[str, Any]] = field(default_factory=list)
    threat_scores: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    fail_on: str | None = None

    async def add_anomaly(self, **kw: Any) -> None:
        if self.fail_on == "anomaly":
            raise RuntimeError("db down")
        self.anomalies.append(kw)

    async def upsert_detection(self, **kw: Any) -> None:
        if self.fail_on == "detection":
            raise RuntimeError("db down")
        self.detections.append(kw)

    async def upsert_threat_score(self, **kw: Any) -> None:
        self.threat_scores.append(kw)

    async def ensure_alert(self, **kw: Any) -> bool:
        self.alerts.append(kw)
        return True


class FakeInference:
    def __init__(self, score: AnomalyScore | None = None) -> None:
        self._score = score
        self.calls: list[tuple[str, str]] = []

    async def score(self, tenant_id: str, kind: CanonicalKind, features: list[float]) -> AnomalyScore | None:
        self.calls.append((tenant_id, kind.value))
        return self._score


class FakeConsumer:
    group_id = "detection"

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...
    async def run(self, handler: Any) -> None: ...


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "detection-engine", "pg_password": "x",
        "internal_jwt_signing_key": "detection-engine-test-signing-key-0123456789",
        "oidc_client_secret": "s", "neo4j_password": "x",
        "kafka_consumer_group": "detection",
        "detection_min_samples": 10, "detection_window_size": 64,
        "detection_rule_window_s": 300,
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


@dataclass
class Rig:
    engine: DetectionEngine
    repo: FakeRepo
    producer: FakeProducer
    inference: FakeInference
    windows: FeatureWindows
    timeline: EventTimeline
    metrics: Any


@pytest.fixture
def rig() -> Rig:
    settings = build_settings()
    base = build_metrics("detection-engine")
    dm = DetectionMetrics(base, "detection-engine")
    repo = FakeRepo()
    producer = FakeProducer()
    inference = FakeInference()
    windows = FeatureWindows(size=settings.detection_window_size)
    timeline = EventTimeline(window_s=settings.detection_rule_window_s)
    engine = DetectionEngine(
        settings=settings, repository=repo, producer=producer,  # type: ignore[arg-type]
        inference=inference, metrics=dm, windows=windows, timeline=timeline,  # type: ignore[arg-type]
    )
    return Rig(engine=engine, repo=repo, producer=producer, inference=inference,
               windows=windows, timeline=timeline, metrics=base)


async def warm(rig: Rig, kind: CanonicalKind, n: int, *, bytes_sent: int = 1000, **attrs: Any) -> None:
    """Push `n` benign, mildly-varying events so the statistical window is primed
    (a window of identical vectors has zero MAD and can never flag an outlier)."""
    for i in range(n):
        env = canonical(
            kind, actor=("host", f"h{i % 3}"), target=("ip", f"10.0.0.{i % 5}"),
            attributes={"bytes_sent": bytes_sent + (i % 7) * 40, "bytes_received": 200 + (i % 5) * 10,
                        **attrs},
            action="connected_to", outcome="allow",
        )
        await rig.engine.handle(record_for(env))


def anomaly_score(*, method: str = "isolation_forest", normalized: float, is_anomaly: bool) -> AnomalyScore:
    from sm_contracts import AnomalyMethod

    return AnomalyScore(
        method=AnomalyMethod(method), score=normalized * 5, normalized_score=normalized,
        threshold=3.5, is_anomaly=is_anomaly, model_version="test-1", contributing_features=[],
    )


__all__ = [
    "TENANT_ID", "Rig", "anomaly_score", "canonical", "extract_features",
    "record_for", "warm",
]
