"""Phase-13 schema: threat memory (patterns, campaigns, adversary fingerprints).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-11

Notes
-----
- `memory-service` is the only writer. `threat_memory` (a behavioral pattern
  per subject, upserted), `campaign` (a set of related attack chains), and
  `adversary_fingerprint` (one evolving fingerprint per subject) are three
  distinct record kinds — never a shared "memory" table — matching
  `docs/ARCHITECTURE_DECISIONS.md` ADR-011's split between the operational
  graph, the knowledge graph, and threat memory.
- `feature_vector` is `pgvector`'s `vector(32)` type
  (`sm_ml.memory.FEATURE_VECTOR_DIM`) with an HNSW cosine index for
  similarity search. `CREATE EXTENSION IF NOT EXISTS vector` runs first; if
  the running Postgres genuinely lacks the extension this migration fails
  loudly (the CI/compose Postgres image ships it — `pgvector/pgvector:pg16`)
  rather than silently creating a table it cannot index. The *application*
  layer (`MemoryRepository`) is what degrades to an exact-match query when
  an index-backed search errors at query time, not this migration.
- Every table is append-lite (upserted, not append-only) and tenant-scoped
  with `ondelete="RESTRICT"` — the same convention as every other Phase 6+
  table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"
_PATTERN_KIND = "'technique_sequence'"
_CAMPAIGN_STATUS = "'active', 'dormant', 'closed'"
_DIM = 32


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "threat_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("pattern_kind", sa.String(length=32), nullable=False),
        sa.Column("technique_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                   server_default=sa.text("'[]'::jsonb")),
        sa.Column("feature_vector", Vector(_DIM), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_threat_memory"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_threat_memory_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_threat_memory_subject_type"),
        sa.CheckConstraint(f"pattern_kind IN ({_PATTERN_KIND})", name="ck_threat_memory_pattern_kind"),
    )
    op.create_index(
        "ix_threat_memory_tenant_subject", "threat_memory",
        ["tenant_id", "subject_type", "subject_id", "pattern_kind"], unique=True,
    )
    op.create_index("ix_threat_memory_tenant_last_seen", "threat_memory", ["tenant_id", "last_seen"])
    op.create_index(
        "ix_threat_memory_feature_vector", "threat_memory", ["feature_vector"],
        postgresql_using="hnsw", postgresql_ops={"feature_vector": "vector_cosine_ops"},
    )

    op.create_table(
        "campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("chain_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                   server_default=sa.text("'[]'::jsonb")),
        sa.Column("technique_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                   server_default=sa.text("'[]'::jsonb")),
        sa.Column("feature_vector", Vector(_DIM), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_campaign"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_campaign_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"status IN ({_CAMPAIGN_STATUS})", name="ck_campaign_status"),
    )
    op.create_index("ix_campaign_tenant_status", "campaign", ["tenant_id", "status"])
    op.create_index("ix_campaign_tenant_last_seen", "campaign", ["tenant_id", "last_seen"])
    op.create_index(
        "ix_campaign_feature_vector", "campaign", ["feature_vector"],
        postgresql_using="hnsw", postgresql_ops={"feature_vector": "vector_cosine_ops"},
    )

    op.create_table(
        "adversary_fingerprint",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("technique_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                   server_default=sa.text("'[]'::jsonb")),
        sa.Column("campaign_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                   server_default=sa.text("'[]'::jsonb")),
        sa.Column("feature_vector", Vector(_DIM), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_adversary_fingerprint"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"],
            name="fk_adversary_fingerprint_tenant_id_tenant", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"subject_type IN ({_SUBJECT_TYPE})", name="ck_adversary_fingerprint_subject_type"
        ),
    )
    op.create_index(
        "ix_adversary_fingerprint_tenant_subject", "adversary_fingerprint",
        ["tenant_id", "subject_type", "subject_id"], unique=True,
    )
    op.create_index(
        "ix_adversary_fingerprint_tenant_last_seen", "adversary_fingerprint",
        ["tenant_id", "last_seen"],
    )
    op.create_index(
        "ix_adversary_fingerprint_feature_vector", "adversary_fingerprint", ["feature_vector"],
        postgresql_using="hnsw", postgresql_ops={"feature_vector": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("adversary_fingerprint")
    op.drop_table("campaign")
    op.drop_table("threat_memory")
    op.execute("DROP EXTENSION IF EXISTS vector")
