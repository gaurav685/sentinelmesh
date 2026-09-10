"""Phase-11 schema: threat-hunting history.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-10

Notes
-----
- `api-gateway` is the only writer. One append-only row per `/api/v1/soc/hunt`
  call: what was asked (mode + optional natural-language text + resolved intent)
  and the shape of the answer (supported? row_count, cypher_fingerprint) —
  never the result rows themselves.
- `mode` is `varchar` + `CHECK` (`'quick'` | `'nl'`), same convention as the
  other enum columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hunt_query",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal", sa.String(length=256), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("nl_query", sa.Text(), nullable=True),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cypher_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hunt_query"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_hunt_query_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("mode IN ('quick', 'nl')", name="ck_hunt_query_mode"),
    )
    op.create_index("ix_hunt_query_tenant_created", "hunt_query", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_hunt_query_tenant_created", table_name="hunt_query")
    op.drop_table("hunt_query")
