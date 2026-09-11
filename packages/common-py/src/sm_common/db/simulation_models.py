"""SQLAlchemy models for deception decoys (Phase 12).

Owner (`docs/architecture/service-catalog.md`): `simulation-service`.

A `DecoyRow` is a registered piece of deception infrastructure. Its
`network_boundary` column carries the same `CHECK` allow-list as the contract's
`NetworkBoundary` Literal — **`'production'` is not in the allowed set**, so a
decoy can never be recorded as attached to production even if a future caller
bypasses the API schema. `DecoyInteractionRow` is an append-only capture of
attacker interaction with a decoy; a torn-down decoy still keeps its history.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = ["DecoyInteractionRow", "DecoyRow"]

_JSONB = postgresql.JSONB(astext_type=None)
_KIND = "'honeypot_host', 'honeytoken', 'decoy_credential'"
# 'production' is deliberately absent — see the module docstring.
_BOUNDARY = "'isolated', 'dmz-isolated'"
_STATUS = "'active', 'torn_down'"


class DecoyRow(TimestampMixin, Base):
    __tablename__ = "decoy"

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT", name="fk_decoy_tenant_id_tenant"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    network_boundary: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sa_text("'active'"))
    ttl_seconds: Mapped[int] = mapped_column(Integer(), nullable=False, server_default=sa_text("86400"))
    tags: Mapped[list[str]] = mapped_column(_JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    torn_down_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_KIND})", name="ck_decoy_kind"),
        CheckConstraint(f"network_boundary IN ({_BOUNDARY})", name="ck_decoy_network_boundary"),
        CheckConstraint(f"status IN ({_STATUS})", name="ck_decoy_status"),
        Index("ix_decoy_tenant_status", "tenant_id", "status"),
    )


class DecoyInteractionRow(Base):
    __tablename__ = "decoy_interaction"

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    decoy_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("decoy.id", ondelete="RESTRICT", name="fk_decoy_interaction_decoy_id_decoy"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT", name="fk_decoy_interaction_tenant_id_tenant"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    technique_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, str]] = mapped_column(
        _JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")
    )
    #: One-way export only — nothing reads this table back into a production
    #: decision path in this build.
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )

    __table_args__ = (Index("ix_decoy_interaction_decoy_captured", "decoy_id", "captured_at"),)
