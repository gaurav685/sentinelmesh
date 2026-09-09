"""SQLAlchemy models for the detection domain (Phase 5).

System of record for `detection-engine` (`docs/architecture/service-catalog.md`):
`detection`, `anomaly`, `threat_score`, `security_alert`. `detection-engine` is
the only writer; `api-gateway` builds a read projection from the `detections`
Kafka topic, it does not write here.

Same conventions as `models.py`: enum columns are `varchar` + `CHECK` (values
sourced from `sm_contracts` so schema and contract cannot drift), `updated_at` is
trigger-maintained (migration 0003), UUIDv7 primary keys.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sm_contracts import (
    AlertStatus,
    AnomalyMethod,
    DetectionStatus,
    DetectorKind,
    ScoringStatus,
    Severity,
    ThreatSubjectType,
)

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = ["Anomaly", "Detection", "SecurityAlert", "ThreatScore"]

_TIMESTAMP_TABLES = ("detection", "anomaly", "threat_score", "security_alert")


def _in_values(column: str, enum_cls: type[StrEnum]) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum_cls)
    return f"{column} IN ({values})"


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=False,
    )


class Detection(TimestampMixin, Base):
    __tablename__ = "detection"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = _tenant_fk()
    detector: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    scoring_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{ScoringStatus.ok.value}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{DetectionStatus.new.value}'")
    )
    entities: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    technique_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    raw_event_id: Mapped[UUID | None] = mapped_column(postgresql.UUID(as_uuid=True), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(nullable=False)
    last_seen: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint(_in_values("detector", DetectorKind), name="detector"),
        CheckConstraint(_in_values("severity", Severity), name="severity"),
        CheckConstraint(_in_values("scoring_status", ScoringStatus), name="scoring_status"),
        CheckConstraint(_in_values("status", DetectionStatus), name="status"),
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="score_range"),
        Index("ix_detection_tenant_id_created_at", "tenant_id", text("created_at DESC")),
        Index("ix_detection_tenant_id_severity_status", "tenant_id", "severity", "status"),
        Index("ix_detection_tenant_id_dedup_key", "tenant_id", "dedup_key"),
    )


class Anomaly(TimestampMixin, Base):
    __tablename__ = "anomaly"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = _tenant_fk()
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    entity: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_event_id: Mapped[UUID | None] = mapped_column(postgresql.UUID(as_uuid=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(_in_values("method", AnomalyMethod), name="method"),
        CheckConstraint(
            "normalized_score >= 0.0 AND normalized_score <= 1.0", name="normalized_score_range"
        ),
        Index("ix_anomaly_tenant_id_observed_at", "tenant_id", text("observed_at DESC")),
        Index("ix_anomaly_tenant_id_is_anomaly", "tenant_id", "is_anomaly"),
    )


class ThreatScore(TimestampMixin, Base):
    __tablename__ = "threat_score"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = _tenant_fk()
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(256), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    weights_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scoring_status: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint(_in_values("subject_type", ThreatSubjectType), name="subject_type"),
        CheckConstraint(_in_values("scoring_status", ScoringStatus), name="scoring_status"),
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="score_range"),
        UniqueConstraint("tenant_id", "subject_type", "subject_id", name="uq_threat_score_subject"),
        Index("ix_threat_score_tenant_id_score", "tenant_id", text("score DESC")),
    )


class SecurityAlert(TimestampMixin, Base):
    __tablename__ = "security_alert"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = _tenant_fk()
    detection_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("detection.id", ondelete="CASCADE"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{AlertStatus.open.value}'")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    opened_at: Mapped[datetime] = mapped_column(nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(_in_values("severity", Severity), name="severity"),
        CheckConstraint(_in_values("status", AlertStatus), name="status"),
        UniqueConstraint("detection_id", name="uq_security_alert_detection_id"),
        Index("ix_security_alert_tenant_id_status_opened_at", "tenant_id", "status", text("opened_at DESC")),
    )
