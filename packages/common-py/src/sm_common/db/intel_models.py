"""SQLAlchemy models for threat intelligence + MITRE ATT&CK (Phase 6).

Owners (`docs/architecture/service-catalog.md`):
- `mitre-service`: `attack_tactic`, `attack_technique`, `attack_matrix_version`,
  `technique_mapping`.
- `threat-intel-service`: `threat_indicator`, `threat_actor`, `ti_campaign`,
  `ti_source`.

The ATT&CK catalog tables are global (no `tenant_id`) and replaced wholesale by
an import run. `technique_mapping` and the tenant-submittable intel rows are
tenant-scoped. Indicators with a NULL `tenant_id` are platform-global.
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
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sm_contracts import (
    IndicatorType,
    MappingConfidence,
    MappingSource,
    MappingSubjectType,
    TiConfidence,
    TiSourceKind,
)

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = [
    "AttackMatrixVersionRow",
    "AttackTacticRow",
    "AttackTechniqueRow",
    "TechniqueMappingRow",
    "ThreatActorRow",
    "ThreatIndicatorRow",
    "TiCampaignRow",
    "TiSourceRow",
]

_TIMESTAMP_TABLES = (
    "technique_mapping",
    "ti_source",
    "threat_actor",
    "threat_indicator",
    "ti_campaign",
)


def _in_values(column: str, enum_cls: type[StrEnum]) -> str:
    return f"{column} IN (" + ", ".join(f"'{m.value}'" for m in enum_cls) + ")"


# --------------------------------------------------------------------------- #
# MITRE catalog (global, import-replaced)
# --------------------------------------------------------------------------- #
class AttackTacticRow(Base):
    __tablename__ = "attack_tactic"

    tactic_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    shortname: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    matrix_version: Mapped[str] = mapped_column(String(32), nullable=False)


class AttackTechniqueRow(Base):
    __tablename__ = "attack_technique"

    technique_id: Mapped[str] = mapped_column(String(9), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tactic_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    is_subtechnique: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    parent_technique_id: Mapped[str | None] = mapped_column(String(5), nullable=True)
    matrix_version: Mapped[str] = mapped_column(String(32), nullable=False)
    deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class AttackMatrixVersionRow(Base):
    __tablename__ = "attack_matrix_version"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(nullable=False)
    tactic_count: Mapped[int] = mapped_column(Integer, nullable=False)
    technique_count: Mapped[int] = mapped_column(Integer, nullable=False)
    subtechnique_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stix_bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class TechniqueMappingRow(TimestampMixin, Base):
    __tablename__ = "technique_mapping"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)
    technique_id: Mapped[str] = mapped_column(String(9), nullable=False)
    tactic_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    matrix_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        CheckConstraint(_in_values("subject_type", MappingSubjectType), name="ck_technique_mapping_subject_type"),
        CheckConstraint(_in_values("confidence", MappingConfidence), name="ck_technique_mapping_confidence"),
        CheckConstraint(_in_values("source", MappingSource), name="ck_technique_mapping_source"),
        UniqueConstraint(
            "tenant_id", "subject_type", "subject_id", "technique_id", "source",
            name="uq_technique_mapping_subject_technique_source",
        ),
    )


# --------------------------------------------------------------------------- #
# threat intelligence
# --------------------------------------------------------------------------- #
class TiSourceRow(TimestampMixin, Base):
    __tablename__ = "ti_source"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    last_poll_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_poll_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indicator_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(_in_values("kind", TiSourceKind), name="ck_ti_source_kind"),
        CheckConstraint("ttl_seconds >= 60", name="ck_ti_source_ttl_min"),
    )


class ThreatActorRow(TimestampMixin, Base):
    __tablename__ = "threat_actor"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    first_seen: Mapped[datetime | None] = mapped_column(nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(nullable=True)


class ThreatIndicatorRow(TimestampMixin, Base):
    __tablename__ = "threat_indicator"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(2048), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    reputation: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    first_seen: Mapped[datetime] = mapped_column(nullable=False)
    last_seen: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(2200), nullable=False, unique=True)

    __table_args__ = (
        CheckConstraint(_in_values("type", IndicatorType), name="ck_threat_indicator_type"),
        CheckConstraint(_in_values("confidence", TiConfidence), name="ck_threat_indicator_confidence"),
        CheckConstraint("reputation >= 0.0 AND reputation <= 1.0", name="ck_threat_indicator_reputation"),
    )


class TiCampaignRow(TimestampMixin, Base):
    __tablename__ = "ti_campaign"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    first_seen: Mapped[datetime | None] = mapped_column(nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_ti_campaign_tenant_name"),
    )
