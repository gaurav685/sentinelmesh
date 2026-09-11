"""Phase-14 schema: generated reports + report templates.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-11

Notes
-----
- `reporting-service` is the only writer. `report_template` is the fixed,
  seeded set of section layouts (one default row per `ReportKind`); `report`
  is one row per generated report, holding the assembled
  `sm_contracts.report.Report` body as JSONB (a report is a point-in-time
  snapshot, never queried by its internal fields — see
  `sm_common.db.report_models` for why it isn't normalized further).
- The rendered PDF artifact lives in object storage (ADR-019), not
  Postgres; `report.storage_key` is the pointer to it.
- Same tenant-scoped, `ondelete="RESTRICT"` convention as every other
  Phase 6+ table. `report.requested_by` additionally restricts against
  `user.id` — a report always traces back to the principal who asked for
  it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REPORT_KIND = "'incident', 'executive_summary', 'soc', 'compliance'"
_REPORT_STATUS = "'pending', 'partial', 'complete', 'failed'"
_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"

_SEED_NAMESPACE = UUID("8a3d5f1e-6c2b-4e9a-9f7d-1b5c8e2a4d6f")

#: One default template per report kind — the fixed section list this
#: phase renders. A missing content dependency drops a section into
#: `report.missing_sections` at generation time; it is never fabricated.
_TEMPLATES: dict[str, list[str]] = {
    "incident": [
        "metadata", "timeline", "affected_assets", "detections", "evidence",
        "attack_chain", "attack_mappings", "threat_score", "findings",
        "recommendations", "confidence", "provenance",
    ],
    "executive_summary": [
        "metadata", "threat_score", "findings", "recommendations", "confidence", "provenance",
    ],
    "soc": [
        "metadata", "timeline", "affected_assets", "detections", "evidence",
        "attack_chain", "attack_mappings", "threat_score", "findings",
        "recommendations", "confidence", "provenance",
    ],
    "compliance": [
        "metadata", "timeline", "evidence", "attack_mappings",
        "findings", "recommendations", "confidence", "provenance",
    ],
}


def _template_id(kind: str) -> UUID:
    return uuid5(_SEED_NAMESPACE, f"report_template:{kind}:default")


#: Seeding a JSONB column needs an explicit `CAST(... AS jsonb)` in the SQL
#: text rather than `op.bulk_insert` with a JSONB-typed table proxy: online,
#: asyncpg binds the parameter as text and Postgres refuses the *implicit*
#: text->jsonb assignment cast for a bound parameter (only a literal gets
#: that); offline (`--sql` mode), a raw Python list has no literal
#: renderer at all. An explicit cast in the SQL text works unchanged in
#: both modes.
_INSERT_TEMPLATE = sa.text(
    "INSERT INTO report_template (id, kind, name, version, sections, is_default) "
    "VALUES (:id, :kind, :name, :version, CAST(:sections AS jsonb), :is_default)"
)


def upgrade() -> None:
    op.create_table(
        "report_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_report_template"),
        sa.CheckConstraint(f"kind IN ({_REPORT_KIND})", name="ck_report_template_kind"),
    )
    op.create_index(
        "ix_report_template_kind_default", "report_template", ["kind", "is_default"], unique=True
    )

    op.create_table(
        "report",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "body", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "missing_sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_report"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_report_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["user.id"], name="fk_report_requested_by_user", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["report_template.id"],
            name="fk_report_template_id_report_template", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"kind IN ({_REPORT_KIND})", name="ck_report_kind"),
        sa.CheckConstraint(f"status IN ({_REPORT_STATUS})", name="ck_report_status"),
        sa.CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_report_subject_type"),
    )
    op.create_index("ix_report_tenant_created", "report", ["tenant_id", "created_at"])
    op.create_index("ix_report_tenant_subject", "report", ["tenant_id", "subject_type", "subject_id"])

    for kind, sections in _TEMPLATES.items():
        op.execute(
            _INSERT_TEMPLATE.bindparams(
                id=_template_id(kind),
                kind=kind,
                name=f"Default {kind.replace('_', ' ')} template",
                version="1",
                sections=json.dumps(sections),
                is_default=True,
            )
        )


def downgrade() -> None:
    op.drop_table("report")
    op.drop_table("report_template")
