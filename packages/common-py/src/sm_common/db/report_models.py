"""SQLAlchemy models for generated reports (Phase 14; reqs 22, 33).

Owner (`docs/architecture/service-catalog.md`): `reporting-service`. Two
tables:

- `report_template`: the fixed set of section layouts reporting-service
  renders from, one row per `kind`. Seeded by this migration; not
  user-editable in this phase.
- `report`: one row per generated report. The full assembled content
  (timeline, evidence, findings, ...) is the `sm_contracts.report.Report`
  body, stored as JSONB here rather than normalized — a report is a
  point-in-time snapshot, never queried by its internal fields, only by
  `id` / `tenant_id` / `subject_type` + `subject_id` / `kind` / `status`.
  The rendered PDF itself lives in object storage (ADR-019) at
  `storage_key`; this row is the durable record of what was generated and
  how sure the platform was about each part of it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = ["ReportRow", "ReportTemplateRow"]

_JSONB = postgresql.JSONB(astext_type=None)
_REPORT_KIND = "'incident', 'executive_summary', 'soc', 'compliance'"
_REPORT_STATUS = "'pending', 'partial', 'complete', 'failed'"
_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"


class ReportTemplateRow(TimestampMixin, Base):
    __tablename__ = "report_template"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Ordered list of section names this template renders — reporting-service
    #: skips a section it has no content for and records it in
    #: `report.missing_sections` rather than fabricating one.
    sections: Mapped[list[str]] = mapped_column(_JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("true"))

    __table_args__ = (
        CheckConstraint(f"kind IN ({_REPORT_KIND})", name="ck_report_template_kind"),
        Index("ix_report_template_kind_default", "kind", "is_default", unique=True),
    )


class ReportRow(TimestampMixin, Base):
    __tablename__ = "report"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT", name="fk_report_tenant_id_tenant"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sa_text("'pending'"))
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT", name="fk_report_requested_by_user"),
        nullable=False,
    )
    template_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("report_template.id", ondelete="RESTRICT", name="fk_report_template_id_report_template"),
        nullable=True,
    )
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    #: The assembled `sm_contracts.report.Report` body (everything but the
    #: identity/status columns above), stored whole — see module docstring.
    body: Mapped[dict[str, object]] = mapped_column(_JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    missing_sections: Mapped[list[str]] = mapped_column(
        _JSONB, nullable=False, server_default=sa_text("'[]'::jsonb")
    )
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_REPORT_KIND})", name="ck_report_kind"),
        CheckConstraint(f"status IN ({_REPORT_STATUS})", name="ck_report_status"),
        CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_report_subject_type"),
        Index("ix_report_tenant_created", "tenant_id", "created_at"),
        Index("ix_report_tenant_subject", "tenant_id", "subject_type", "subject_id"),
    )
