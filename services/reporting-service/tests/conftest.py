from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from sm_common.config import AppSettings
from sm_common.errors import DependencyUnavailable
from sm_common.observability import build_metrics
from sm_common.security import mint_internal_token
from sm_contracts import Detection, EvidenceItem, Report, Severity, ThreatScore
from sm_reporting_service.metrics import ReportMetrics
from sm_reporting_service.repository import ReportBody

_TEST_JWT_KEY = "reporting-service-test-signing-key-0123456789abcd"
_NOW = datetime.now(UTC)


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "reporting-service",
        "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY,
        "oidc_client_secret": "s",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


def token(*, audience: str = "reporting-service", key: str = _TEST_JWT_KEY, tenant: Any = None) -> str:
    return mint_internal_token(
        signing_key=key, subject="api-gateway", tenant_id=tenant or uuid.uuid4(), audience=audience,
    )


def detection(tenant_id: Any, **over: Any) -> Detection:
    base: dict[str, Any] = dict(
        id=uuid.uuid4(), tenant_id=tenant_id, created_at=_NOW, updated_at=_NOW,
        detector="rule", rule_id="r1", title="Suspicious login", description="brute force",
        severity=Severity.high, score=0.8, scoring_status="ok", status="new",
        entities=[], technique_ids=["T1110"],
        evidence=[EvidenceItem(
            kind="rule_match", ref="rule:brute-force", summary="rule fired", provenance="detection-engine:r1",
        )],
        raw_event_id=None, dedup_key="dk1", first_seen=_NOW, last_seen=_NOW,
    )
    base.update(over)
    return Detection(**base)


def threat_score(tenant_id: Any, **over: Any) -> ThreatScore:
    base: dict[str, Any] = dict(
        id=uuid.uuid4(), tenant_id=tenant_id, created_at=_NOW, updated_at=_NOW,
        subject_type="host", subject_id="web01", score=0.6, components={"base": 0.6},
        weights_version="v1", scoring_status="ok", computed_at=_NOW,
    )
    base.update(over)
    return ThreatScore(**base)


class FakeContentRepository:
    def __init__(self) -> None:
        self.detection_response: Detection | None = None
        self.detections_response: list[Detection] = []
        self.score_response: ThreatScore | None = None

    async def get_detection(self, tenant_id: Any, detection_id: Any) -> Detection | None:
        return self.detection_response

    async def list_detections_for_subject(
        self, tenant_id: Any, *, subject_type: str, subject_id: str, limit: int = 50,
    ) -> list[Detection]:
        return self.detections_response

    async def get_threat_score(
        self, tenant_id: Any, *, subject_type: str, subject_id: str,
    ) -> ThreatScore | None:
        return self.score_response


class FakeContentClient:
    def __init__(self) -> None:
        self.graph_response: dict[str, Any] | None = None
        self.graph_raises = False
        self.techniques_response: list[dict[str, Any]] = []
        self.techniques_raises = False
        self.memory_patterns_response: list[dict[str, Any]] = []
        self.memory_raises = False
        self.lateral_movement_response: dict[str, Any] | None = None
        self.explain_response: dict[str, Any] | None = None
        self.explain_raises = False

    async def graph_neighbors(self, tenant_id: Any, *, label: str, key: str, depth: int = 1) -> Any:
        if self.graph_raises:
            raise DependencyUnavailable("graph-service unreachable")
        return self.graph_response

    async def mitre_techniques(self, tenant_id: Any) -> list[dict[str, Any]]:
        if self.techniques_raises:
            raise DependencyUnavailable("mitre-service unreachable")
        return self.techniques_response

    async def explain(self, tenant_id: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.explain_raises:
            raise DependencyUnavailable("ai-analyst unreachable")
        return self.explain_response

    async def memory_patterns(self, tenant_id: Any, *, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
        if self.memory_raises:
            raise DependencyUnavailable("memory-service unreachable")
        return self.memory_patterns_response

    async def predict_lateral_movement(
        self, tenant_id: Any, *, subject_type: str, subject_id: str,
    ) -> dict[str, Any] | None:
        if self.memory_raises:
            raise DependencyUnavailable("memory-service unreachable")
        return self.lateral_movement_response


class FakeObjectStore:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, tuple[str, ...]]] = []
        self.put_raises = False
        self.stored_key: str | None = "tenant/reports/x.pdf"

    async def put_bytes(self, *, bucket: str, key_parts: Any, body: bytes, content_type: str) -> str:
        if self.put_raises:
            raise DependencyUnavailable("object storage write failed")
        self.put_calls.append((bucket, tuple(key_parts)))
        return "/".join(key_parts)

    async def presigned_get_url(self, *, bucket: str, key: str, expires_in: int = 300) -> str:
        return f"https://minio.example/{bucket}/{key}?sig=abc"

    async def ping(self, bucket: str) -> None:
        return None

    async def ensure_bucket(self, bucket: str) -> None:
        return None


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bytes]] = []

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def ping(self) -> None: ...

    async def send(self, topic: str, *, key: str, value: bytes, headers: Any = None) -> None:
        self.sent.append((topic, key, value))


class FakeReportRepository:
    def __init__(self) -> None:
        self.template_sections_response: dict[str, list[str]] = {}
        self._rows: dict[uuid.UUID, Report] = {}

    async def default_template_id(self, kind: str) -> uuid.UUID | None:
        return uuid.uuid4()

    async def template_sections(self, kind: str) -> list[str]:
        return self.template_sections_response.get(kind, [])

    async def create_pending(
        self, tenant_id: Any, *, kind: str, subject_type: str, subject_id: str,
        title: str, requested_by: Any,
    ) -> Report:
        report = Report(
            id=uuid.uuid4(), tenant_id=tenant_id, created_at=_NOW, updated_at=_NOW,
            kind=kind, status="pending", subject_type=subject_type, subject_id=subject_id,
            title=title, requested_by=requested_by, generated_at=None,
        )
        self._rows[report.id] = report
        return report

    async def get(self, tenant_id: Any, report_id: Any) -> Report | None:
        row = self._rows.get(report_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row

    async def save_result(
        self, tenant_id: Any, report_id: Any, *, status: str, body: ReportBody,
        missing_sections: list[str], storage_key: str | None, generated_at: datetime,
    ) -> Report:
        row = self._rows[report_id]
        updated = row.model_copy(update={
            "status": status, "generated_at": generated_at, "storage_key": storage_key,
            "missing_sections": missing_sections,
            "incident_metadata": body.incident_metadata, "timeline": body.timeline,
            "affected_assets": body.affected_assets, "detection_ids": body.detection_ids,
            "evidence": body.evidence, "chain_ids": body.chain_ids,
            "technique_ids": body.technique_ids, "threat_score": body.threat_score,
            "findings": body.findings, "recommendations": body.recommendations,
            "confidence": body.confidence, "provenance": body.provenance,
        })
        self._rows[report_id] = updated
        return updated


class _FakeDb:
    async def ping(self) -> None: ...
    async def dispose(self) -> None: ...


@pytest.fixture
def content_repo() -> FakeContentRepository:
    return FakeContentRepository()


@pytest.fixture
def content() -> FakeContentClient:
    return FakeContentClient()


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def producer() -> FakeProducer:
    return FakeProducer()


@pytest.fixture
def repo() -> FakeReportRepository:
    return FakeReportRepository()


@pytest.fixture
def generator(
    repo: FakeReportRepository, content_repo: FakeContentRepository, content: FakeContentClient,
    store: FakeObjectStore, producer: FakeProducer,
) -> Any:
    from sm_reporting_service.generator import ReportGenerator

    base = build_metrics("reporting-service")
    return ReportGenerator(
        repo=repo,  # type: ignore[arg-type]
        content_repo=content_repo,  # type: ignore[arg-type]
        content=content,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        producer=producer,  # type: ignore[arg-type]
        metrics=ReportMetrics(base, "reporting-service"), bucket="sm-reports-test",
    )


@pytest.fixture
def client(
    repo: FakeReportRepository, content_repo: FakeContentRepository, content: FakeContentClient,
    store: FakeObjectStore, producer: FakeProducer, generator: Any,
) -> Any:
    from fastapi.testclient import TestClient

    from sm_reporting_service.app import create_app
    from sm_reporting_service.deps import Services

    base = build_metrics("reporting-service")
    services = Services(
        settings=build_settings(), metrics=base, report_metrics=ReportMetrics(base, "reporting-service"),
        db=_FakeDb(),  # type: ignore[arg-type]
        repo=repo,  # type: ignore[arg-type]
        http=None,  # type: ignore[arg-type]
        content_repo=content_repo,  # type: ignore[arg-type]
        content=content,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        producer=producer,  # type: ignore[arg-type]
        generator=generator,
    )
    c = TestClient(create_app(services=services))
    with c:
        yield c
