"""SQLAlchemy models for attack-chain correlation (Phase 7; req 6).

Owner (`docs/architecture/service-catalog.md`): `correlation-engine`.

`attack_chain` is one multi-stage chain about one subject inside one tumbling
window; `attack_chain_stage` is one kill-chain stage within a chain, holding the
ids of the detections that placed it there. Both are tenant-scoped. The chain id
is deterministic (`sm_contracts.chain_id_for`) so an at-least-once reprocess
upserts rather than duplicating.

Same conventions as the other model modules: enum columns are `varchar` + `CHECK`
(values sourced from `sm_contracts`), `updated_at` is trigger-maintained
(migration 0005), score / confidence / progression are range-checked in `[0, 1]`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sm_contracts import AttackStage, ChainStatus, ScoringStatus, Severity, ThreatSubjectType

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = ["AttackChainRow", "AttackChainStageRow"]

_TIMESTAMP_TABLES = ("attack_chain", "attack_chain_stage")


def _in_values(column: str, enum_cls: type[StrEnum]) -> str:
    return f"{column} IN (" + ", ".join(f"'{m.value}'" for m in enum_cls) + ")"


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=False,
    )


class AttackChainRow(TimestampMixin, Base):
    __tablename__ = "attack_chain"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = _tenant_fk()
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    first_seen: Mapped[datetime] = mapped_column(nullable=False)
    last_seen: Mapped[datetime] = mapped_column(nullable=False)
    distinct_stage_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    progression: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    score_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scoring_status: Mapped[str] = mapped_column(String(16), nullable=False)
    technique_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    detection_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    notes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    __table_args__ = (
        CheckConstraint(_in_values("subject_type", ThreatSubjectType), name="ck_attack_chain_subject_type"),
        CheckConstraint(_in_values("status", ChainStatus), name="ck_attack_chain_status"),
        CheckConstraint(_in_values("scoring_status", ScoringStatus), name="ck_attack_chain_scoring_status"),
        CheckConstraint("progression >= 0.0 AND progression <= 1.0", name="ck_attack_chain_progression"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_attack_chain_confidence"),
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_attack_chain_score"),
        UniqueConstraint(
            "tenant_id", "subject_type", "subject_id", "window_start",
            name="uq_attack_chain_subject_window",
        ),
        Index("ix_attack_chain_tenant_id_last_seen", "tenant_id", text("last_seen DESC")),
        Index("ix_attack_chain_tenant_id_score", "tenant_id", text("score DESC")),
    )


class AttackChainStageRow(TimestampMixin, Base):
    __tablename__ = "attack_chain_stage"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    chain_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("attack_chain.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = _tenant_fk()
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False)
    detection_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    technique_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    max_severity: Mapped[str] = mapped_column(String(16), nullable=False)
    detection_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    first_seen: Mapped[datetime] = mapped_column(nullable=False)
    last_seen: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint(_in_values("stage", AttackStage), name="ck_attack_chain_stage_stage"),
        CheckConstraint(_in_values("max_severity", Severity), name="ck_attack_chain_stage_severity"),
        UniqueConstraint("chain_id", "stage", name="uq_attack_chain_stage_chain_stage"),
        Index("ix_attack_chain_stage_chain_id", "chain_id"),
    )
