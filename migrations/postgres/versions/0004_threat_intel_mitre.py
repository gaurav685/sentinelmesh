"""Phase-6 schema: threat intelligence + MITRE ATT&CK.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-09

Notes
-----
- MITRE catalog tables (`attack_tactic`, `attack_technique`,
  `attack_matrix_version`) are **global** (no `tenant_id`) and replaced wholesale
  by an import run (`scripts/import_attack_stix.py`). No ATT&CK data ships here.
- `technique_mapping` and the tenant-submittable intel rows are tenant-scoped.
  A `threat_indicator` with NULL `tenant_id` is platform-global.
- `freshness` is derived on read (age vs. the source TTL), not stored.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICATOR_TYPE = "'ipv4', 'ipv6', 'domain', 'url', 'sha256', 'sha1', 'md5', 'email'"
_TI_CONFIDENCE = "'low', 'medium', 'high'"
_TI_SOURCE_KIND = "'feed', 'api', 'manual', 'fixture'"
_MAP_CONFIDENCE = "'low', 'medium', 'high'"
_MAP_SOURCE = "'rule', 'graph', 'feature', 'llm', 'analyst'"
_MAP_SUBJECT = "'detection', 'attack_chain'"

_TIMESTAMP_TABLES = ("technique_mapping", "ti_source", "threat_actor", "threat_indicator", "ti_campaign")

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def _ts_cols() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    # ---- MITRE catalog (global) ---------------------------------------
    op.create_table(
        "attack_tactic",
        sa.Column("tactic_id", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("shortname", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("matrix_version", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("tactic_id", name="pk_attack_tactic"),
    )
    op.create_table(
        "attack_technique",
        sa.Column("technique_id", sa.String(length=9), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tactic_ids", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("is_subtechnique", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("parent_technique_id", sa.String(length=5), nullable=True),
        sa.Column("matrix_version", sa.String(length=32), nullable=False),
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("technique_id", name="pk_attack_technique"),
    )
    op.create_index("ix_attack_technique_is_subtechnique", "attack_technique", ["is_subtechnique"])
    op.create_table(
        "attack_matrix_version",
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tactic_count", sa.Integer(), nullable=False),
        sa.Column("technique_count", sa.Integer(), nullable=False),
        sa.Column("subtechnique_count", sa.Integer(), nullable=False),
        sa.Column("stix_bundle_sha256", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("version", name="pk_attack_matrix_version"),
    )

    # ---- technique_mapping -------------------------------------------
    op.create_table(
        "technique_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technique_id", sa.String(length=9), nullable=False),
        sa.Column("tactic_id", sa.String(length=8), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("rationale", sa.String(length=1000), nullable=False),
        sa.Column("evidence", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("matrix_version", sa.String(length=32), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_technique_mapping"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_technique_mapping_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"subject_type IN ({_MAP_SUBJECT})", name="ck_technique_mapping_subject_type"),
        sa.CheckConstraint(f"confidence IN ({_MAP_CONFIDENCE})", name="ck_technique_mapping_confidence"),
        sa.CheckConstraint(f"source IN ({_MAP_SOURCE})", name="ck_technique_mapping_source"),
        sa.UniqueConstraint(
            "tenant_id", "subject_type", "subject_id", "technique_id", "source",
            name="uq_technique_mapping_subject_technique_source",
        ),
    )
    op.create_index("ix_technique_mapping_tenant_id", "technique_mapping", ["tenant_id"])
    op.create_index("ix_technique_mapping_tenant_id_subject_id", "technique_mapping", ["tenant_id", "subject_id"])
    op.create_index("ix_technique_mapping_technique_id", "technique_mapping", ["technique_id"])

    # ---- ti_source --------------------------------------------------
    op.create_table(
        "ti_source",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_status", sa.String(length=64), nullable=True),
        sa.Column("indicator_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_ti_source"),
        sa.UniqueConstraint("name", name="uq_ti_source_name"),
        sa.CheckConstraint(f"kind IN ({_TI_SOURCE_KIND})", name="ck_ti_source_kind"),
        sa.CheckConstraint("ttl_seconds >= 60", name="ck_ti_source_ttl_min"),
    )

    # ---- threat_actor --------------------------------------------
    op.create_table(
        "threat_actor",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_threat_actor"),
        sa.UniqueConstraint("actor_id", name="uq_threat_actor_actor_id"),
    )

    # ---- threat_indicator --------------------------------------
    op.create_table(
        "threat_indicator",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=2048), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("reputation", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("provenance", _JSONB, nullable=False),
        sa.Column("dedup_key", sa.String(length=2200), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_threat_indicator"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_threat_indicator_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("dedup_key", name="uq_threat_indicator_dedup_key"),
        sa.CheckConstraint(f"type IN ({_INDICATOR_TYPE})", name="ck_threat_indicator_type"),
        sa.CheckConstraint(f"confidence IN ({_TI_CONFIDENCE})", name="ck_threat_indicator_confidence"),
        sa.CheckConstraint("reputation >= 0.0 AND reputation <= 1.0", name="ck_threat_indicator_reputation"),
    )
    op.create_index("ix_threat_indicator_type_value", "threat_indicator", ["type", "value"])
    op.create_index("ix_threat_indicator_tenant_id_type", "threat_indicator", ["tenant_id", "type"])
    op.execute(
        "CREATE INDEX ix_threat_indicator_expires_at ON threat_indicator (expires_at) "
        "WHERE expires_at IS NOT NULL"
    )

    # ---- ti_campaign ------------------------------------------
    op.create_table(
        "ti_campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_ti_campaign"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_ti_campaign_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ti_campaign_tenant_name"),
    )

    for table in _TIMESTAMP_TABLES:
        op.execute(
            f'CREATE TRIGGER trg_{table}_set_updated_at BEFORE UPDATE ON "{table}" '
            f"FOR EACH ROW EXECUTE FUNCTION sm_set_updated_at();"
        )


def downgrade() -> None:
    for table in _TIMESTAMP_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON "{table}"')
    op.drop_table("ti_campaign")
    op.drop_table("threat_indicator")
    op.drop_table("threat_actor")
    op.drop_table("ti_source")
    op.drop_table("technique_mapping")
    op.drop_table("attack_matrix_version")
    op.drop_table("attack_technique")
    op.drop_table("attack_tactic")
