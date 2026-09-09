"""Phase-7 schema: attack-chain correlation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-09

Notes
-----
- `correlation-engine` is the only writer. `attack_chain` is one multi-stage
  chain about one subject in one tumbling window; `attack_chain_stage` is one
  kill-chain stage within it, keeping the ids of the detections behind it.
- The chain id is deterministic (`sm_contracts.chain_id_for`), so an
  at-least-once reprocess upserts. The `(tenant_id, subject_type, subject_id,
  window_start)` unique constraint is a second guard on the same identity.
- Stage assignment is a lookup; `stage = 'unknown'` is a valid stored value for a
  detection whose techniques have no known kill-chain mapping.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"
_CHAIN_STATUS = "'forming', 'active', 'dormant'"
_SCORING_STATUS = "'ok', 'degraded'"
_SEVERITY = "'info', 'low', 'medium', 'high', 'critical'"
_STAGE = (
    "'reconnaissance', 'resource_development', 'initial_access', 'execution', 'persistence', "
    "'privilege_escalation', 'defense_evasion', 'credential_access', 'discovery', "
    "'lateral_movement', 'collection', 'command_and_control', 'exfiltration', 'impact', 'unknown'"
)

_TIMESTAMP_TABLES = ("attack_chain", "attack_chain_stage")

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def _ts_cols() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "attack_chain",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("distinct_stage_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("progression", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("score_version", sa.String(length=32), nullable=False),
        sa.Column("scoring_status", sa.String(length=16), nullable=False),
        sa.Column("technique_ids", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("detection_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("notes", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_attack_chain"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_attack_chain_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_attack_chain_subject_type"),
        sa.CheckConstraint(f"status IN ({_CHAIN_STATUS})", name="ck_attack_chain_status"),
        sa.CheckConstraint(f"scoring_status IN ({_SCORING_STATUS})", name="ck_attack_chain_scoring_status"),
        sa.CheckConstraint("progression >= 0.0 AND progression <= 1.0", name="ck_attack_chain_progression"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_attack_chain_confidence"),
        sa.CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_attack_chain_score"),
        sa.UniqueConstraint(
            "tenant_id", "subject_type", "subject_id", "window_start",
            name="uq_attack_chain_subject_window",
        ),
    )
    op.execute(
        "CREATE INDEX ix_attack_chain_tenant_id_last_seen ON attack_chain (tenant_id, last_seen DESC)"
    )
    op.execute("CREATE INDEX ix_attack_chain_tenant_id_score ON attack_chain (tenant_id, score DESC)")

    op.create_table(
        "attack_chain_stage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("stage_order", sa.Integer(), nullable=False),
        sa.Column("detection_ids", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("technique_ids", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("max_severity", sa.String(length=16), nullable=False),
        sa.Column("detection_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_attack_chain_stage"),
        sa.ForeignKeyConstraint(
            ["chain_id"], ["attack_chain.id"], name="fk_attack_chain_stage_chain_id_attack_chain",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_attack_chain_stage_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"stage IN ({_STAGE})", name="ck_attack_chain_stage_stage"),
        sa.CheckConstraint(f"max_severity IN ({_SEVERITY})", name="ck_attack_chain_stage_severity"),
        sa.UniqueConstraint("chain_id", "stage", name="uq_attack_chain_stage_chain_stage"),
    )
    op.create_index("ix_attack_chain_stage_chain_id", "attack_chain_stage", ["chain_id"])

    for table in _TIMESTAMP_TABLES:
        op.execute(
            f'CREATE TRIGGER trg_{table}_set_updated_at BEFORE UPDATE ON "{table}" '
            f"FOR EACH ROW EXECUTE FUNCTION sm_set_updated_at();"
        )


def downgrade() -> None:
    for table in _TIMESTAMP_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON "{table}"')
    op.drop_table("attack_chain_stage")
    op.drop_table("attack_chain")
