"""Phase-14 schema: attack narratives.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-11

Notes
-----
- `ai-analyst` is the only writer. `narrative` is one row per attack
  chain, upserted every time `GET /api/v1/incidents/{chain_id}/narrative`
  runs — a narrative is a snapshot of the chain's own state, not
  append-only, hence the unique `(tenant_id, chain_id)` index rather than
  a plain foreign key back to `attack_chain` (chains live in a different
  service's tables; this migration does not assume it can reach across
  that boundary with a FK, only a tenant-scoped uniqueness rule).
- `body` holds `beats`/`summary`/`cited_refs`/`confidence`/`model`/
  `degraded`/`degraded_reason`/`simulated` as JSONB — see
  `sm_common.db.narrative_models` for why it isn't normalized further.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"


def upgrade() -> None:
    op.create_table(
        "narrative",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "body", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_narrative"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_narrative_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_narrative_subject_type"),
    )
    op.create_index("ix_narrative_tenant_chain", "narrative", ["tenant_id", "chain_id"], unique=True)


def downgrade() -> None:
    op.drop_table("narrative")
