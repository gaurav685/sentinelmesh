"""SQLAlchemy models for threat memory (Phase 13).

Owner (`docs/architecture/service-catalog.md`): `memory-service`. Three
tenant-scoped record kinds — see `docs/ARCHITECTURE_DECISIONS.md` ADR-011 for
why this is a separate store from the operational/knowledge graph (Neo4j) and
the detection/chain tables (also Postgres, but owned by `detection-engine` /
`correlation-engine`).

`feature_vector` is a `pgvector` column (`CREATE EXTENSION vector`, migration
`0009`) — a fixed-dimension, deterministic hashed-bag-of-techniques vector
(`sm_ml.memory.technique_feature_vector`), never a trained embedding. Every
table degrades to an exact-match query (`sm_ml.memory.cosine_similarity` in
Python) when the extension or its index is unavailable — see
`MemoryRepository.find_similar`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = ["AdversaryFingerprintRow", "CampaignRow", "ThreatMemoryRow"]

_JSONB = postgresql.JSONB(astext_type=None)
_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"
_PATTERN_KIND = "'technique_sequence'"
_CAMPAIGN_STATUS = "'active', 'dormant', 'closed'"

#: `sm_ml.memory.FEATURE_VECTOR_DIM` — kept as a plain int here so this module
#: has no dependency on `sm_ml` (a schema shouldn't need a library import).
FEATURE_VECTOR_DIM = 32


class ThreatMemoryRow(TimestampMixin, Base):
    __tablename__ = "threat_memory"

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT", name="fk_threat_memory_tenant_id_tenant"),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(256), nullable=False)
    pattern_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    technique_ids: Mapped[list[str]] = mapped_column(
        _JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )
    feature_vector: Mapped[list[float]] = mapped_column(Vector(FEATURE_VECTOR_DIM), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default=sa_text("1"))
    first_seen: Mapped[datetime] = mapped_column(nullable=False)
    last_seen: Mapped[datetime] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)

    __table_args__ = (
        CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_threat_memory_subject_type"),
        CheckConstraint(f"pattern_kind IN ({_PATTERN_KIND})", name="ck_threat_memory_pattern_kind"),
        Index(
            "ix_threat_memory_tenant_subject",
            "tenant_id", "subject_type", "subject_id", "pattern_kind",
            unique=True,
        ),
        Index("ix_threat_memory_tenant_last_seen", "tenant_id", "last_seen"),
    )


class CampaignRow(TimestampMixin, Base):
    __tablename__ = "campaign"

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT", name="fk_campaign_tenant_id_tenant"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sa_text("'active'"))
    chain_ids: Mapped[list[str]] = mapped_column(
        _JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )
    technique_ids: Mapped[list[str]] = mapped_column(
        _JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )
    feature_vector: Mapped[list[float]] = mapped_column(Vector(FEATURE_VECTOR_DIM), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(nullable=False)
    last_seen: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint(f"status IN ({_CAMPAIGN_STATUS})", name="ck_campaign_status"),
        Index("ix_campaign_tenant_status", "tenant_id", "status"),
        Index("ix_campaign_tenant_last_seen", "tenant_id", "last_seen"),
    )


class AdversaryFingerprintRow(TimestampMixin, Base):
    __tablename__ = "adversary_fingerprint"

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey(
            "tenant.id", ondelete="RESTRICT", name="fk_adversary_fingerprint_tenant_id_tenant"
        ),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(256), nullable=False)
    technique_ids: Mapped[list[str]] = mapped_column(
        _JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )
    campaign_ids: Mapped[list[str]] = mapped_column(
        _JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )
    feature_vector: Mapped[list[float]] = mapped_column(Vector(FEATURE_VECTOR_DIM), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(nullable=False)
    last_seen: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"subject_type IN ({_SUBJECT_TYPE})", name="ck_adversary_fingerprint_subject_type"
        ),
        Index(
            "ix_adversary_fingerprint_tenant_subject",
            "tenant_id", "subject_type", "subject_id",
            unique=True,
        ),
        Index("ix_adversary_fingerprint_tenant_last_seen", "tenant_id", "last_seen"),
    )
