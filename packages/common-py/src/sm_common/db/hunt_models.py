"""SQLAlchemy model for the threat-hunting history (Phase 11).

Owner: `api-gateway` (the only writer — it records every `/api/v1/soc/hunt`).
Append-only: one row per hunt, no `updated_at`. Tenant-scoped. It stores what was
asked and the shape of the answer — never the result rows themselves.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean as SaBoolean
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import uuid7
from .base import Base

__all__ = ["HuntQueryRow"]


class HuntQueryRow(Base):
    __tablename__ = "hunt_query"

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT", name="fk_hunt_query_tenant_id_tenant"),
        nullable=False,
    )
    #: The requesting principal (user id / email) — for audit.
    principal: Mapped[str] = mapped_column(String(256), nullable=False)
    #: "quick" (structured plan from the UI) or "nl" (natural-language).
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The natural-language text, when `mode = 'nl'`.
    nl_query: Mapped[str | None] = mapped_column(Text(), nullable=True)
    #: The resolved `HuntIntent`, or NULL when the request could not be planned.
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    supported: Mapped[bool] = mapped_column(SaBoolean(), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default=sa_text("0"))
    cypher_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )

    __table_args__ = (
        CheckConstraint("mode IN ('quick', 'nl')", name="ck_hunt_query_mode"),
        Index("ix_hunt_query_tenant_created", "tenant_id", "created_at"),
    )
