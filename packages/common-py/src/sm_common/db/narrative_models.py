"""SQLAlchemy model for attack narratives (Phase 14; req 33).

Owner (`docs/architecture/service-catalog.md`): `ai-analyst`. One row per
attack chain, upserted on every `GET .../narrative` — a narrative is a
snapshot of the chain's own state at generation time, not append-only.
`body` holds everything the `sm_contracts.api.narrative.Narrative`
contract carries beyond the identity/subject columns here: `beats`,
`summary`, `cited_refs`, `confidence`, `model`, `degraded`,
`degraded_reason`, `simulated`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = ["NarrativeRow"]

_JSONB = postgresql.JSONB(astext_type=None)
_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"


class NarrativeRow(TimestampMixin, Base):
    __tablename__ = "narrative"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT", name="fk_narrative_tenant_id_tenant"),
        nullable=False,
    )
    chain_id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(256), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(nullable=False)
    #: `dict[str, Any]`, not a stricter type: non-authoritative JSON,
    #: validated at the trust boundary when read back into the
    #: `Narrative` contract, not in the type system (mirrors
    #: `sm_common.db.report_models.ReportRow.body`).
    body: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))

    __table_args__ = (
        CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_narrative_subject_type"),
        Index("ix_narrative_tenant_chain", "tenant_id", "chain_id", unique=True),
    )
