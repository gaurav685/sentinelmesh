"""Phase-12 schema: deception decoys + interaction capture.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-11

Notes
-----
- `simulation-service` is the only writer. `decoy` is a registered piece of
  deception infrastructure; `decoy_interaction` is an append-only capture of
  attacker interaction with one.
- `decoy.network_boundary` CHECK deliberately excludes `'production'` — a
  decoy can never be recorded as attached to production, at the database
  layer, independent of any application-level validation.
- `decoy_interaction` has no `updated_at` — it is never modified after insert.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND = "'honeypot_host', 'honeytoken', 'decoy_credential'"
# 'production' is deliberately absent.
_BOUNDARY = "'isolated', 'dmz-isolated'"
_STATUS = "'active', 'torn_down'"


def upgrade() -> None:
    op.create_table(
        "decoy",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("network_boundary", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False, server_default=sa.text("86400")),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                   server_default=sa.text("'[]'::jsonb")),
        sa.Column("torn_down_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_decoy"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_decoy_tenant_id_tenant", ondelete="RESTRICT"),
        sa.CheckConstraint(f"kind IN ({_KIND})", name="ck_decoy_kind"),
        sa.CheckConstraint(f"network_boundary IN ({_BOUNDARY})", name="ck_decoy_network_boundary"),
        sa.CheckConstraint(f"status IN ({_STATUS})", name="ck_decoy_status"),
    )
    op.create_index("ix_decoy_tenant_status", "decoy", ["tenant_id", "status"])

    op.create_table(
        "decoy_interaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decoy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=256), nullable=False),
        sa.Column("technique_hint", sa.String(length=64), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                   server_default=sa.text("'{}'::jsonb")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_decoy_interaction"),
        sa.ForeignKeyConstraint(
            ["decoy_id"], ["decoy.id"], name="fk_decoy_interaction_decoy_id_decoy", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_decoy_interaction_tenant_id_tenant", ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_decoy_interaction_decoy_captured", "decoy_interaction", ["decoy_id", "captured_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_decoy_interaction_decoy_captured", table_name="decoy_interaction")
    op.drop_table("decoy_interaction")
    op.drop_index("ix_decoy_tenant_status", table_name="decoy")
    op.drop_table("decoy")
