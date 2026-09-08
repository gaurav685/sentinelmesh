"""Phase-1 control-plane schema: tenant, user, RBAC, sensor, audit_log.

Revision ID: 0001
Revises: None
Create Date: 2026-09-08

Notes
-----
- Enum-valued columns are `varchar` + `CHECK`, not native Postgres enums, so
  adding a value later is a cheap migration instead of a locking `ALTER TYPE`.
- `updated_at` is maintained by a trigger so a write that bypasses the ORM still
  bumps it.
- `audit_log` is append-only: a trigger rejects UPDATE and DELETE regardless of
  table ownership (a `REVOKE` would not bind the table owner).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_STATUS = "'active', 'suspended'"
_USER_STATUS = "'active', 'disabled', 'invited'"
_SENSOR_TYPE = "'network', 'auth', 'dns', 'process', 'file', 'mixed'"
_SENSOR_STATUS = "'active', 'disabled', 'pending'"
_ACTOR_TYPE = "'user', 'sensor', 'service', 'agent', 'system'"
_AUDIT_RESULT = "'allow', 'deny', 'success', 'failure'"
_PERMISSION_CODE = (
    "'users:read', 'users:create', 'users:update', "
    "'roles:read', 'roles:grant', "
    "'sensors:read', 'sensors:manage', "
    "'audit:read', 'ops:read', "
    "'detections:read', 'hunt:query', 'reports:generate', "
    "'response:execute', 'response:approve'"
)

_TIMESTAMP_TABLES = ("tenant", "user", "role", "sensor")


def upgrade() -> None:
    # ---- shared trigger function for updated_at ---------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sm_set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ---- tenant ------------------------------------------------------------
    op.create_table(
        "tenant",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_tenant"),
        sa.UniqueConstraint("slug", name="uq_tenant_slug"),
        sa.CheckConstraint(f"status IN ({_TENANT_STATUS})", name="tenant_status"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'", name="tenant_slug_format"
        ),
    )
    op.create_index("ix_tenant_status", "tenant", ["status"])

    # ---- permission --------------------------------------------------------
    op.create_table(
        "permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permission"),
        sa.UniqueConstraint("code", name="uq_permission_code"),
        sa.CheckConstraint(f"code IN ({_PERMISSION_CODE})", name="permission_code"),
    )

    # ---- role --------------------------------------------------------------
    op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_role"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_role_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "(is_system AND tenant_id IS NULL) OR (NOT is_system AND tenant_id IS NOT NULL)",
            name="role_system_implies_no_tenant",
        ),
    )
    op.create_index("ix_role_tenant_id", "role", ["tenant_id"])
    op.create_index(
        "uq_role_system_name", "role", ["name"], unique=True, postgresql_where=sa.text("tenant_id IS NULL")
    )
    op.create_index(
        "uq_role_tenant_id_name",
        "role",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    # ---- user --------------------------------------------------------------
    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_user"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_user_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_id_email"),
        sa.UniqueConstraint("tenant_id", "external_subject", name="uq_user_tenant_id_external_subject"),
        sa.CheckConstraint(f"status IN ({_USER_STATUS})", name="user_status"),
        sa.CheckConstraint("email = lower(email)", name="user_email_lowercase"),
        sa.CheckConstraint("failed_login_count >= 0", name="user_failed_login_count_nonneg"),
    )
    op.create_index("ix_user_tenant_id", "user", ["tenant_id"])
    op.create_index("ix_user_tenant_id_status", "user", ["tenant_id", "status"])

    # ---- user_role ---------------------------------------------------------
    op.create_table(
        "user_role",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_role"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_user_role_user_id_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name="fk_user_role_role_id_role", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["user.id"], name="fk_user_role_granted_by_user", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_user_role_role_id", "user_role", ["role_id"])

    # ---- role_permission ---------------------------------------------------
    op.create_table(
        "role_permission",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permission"),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name="fk_role_permission_role_id_role", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permission.id"],
            name="fk_role_permission_permission_id_permission",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_role_permission_permission_id", "role_permission", ["permission_id"])

    # ---- sensor ------------------------------------------------------------
    op.create_table(
        "sensor",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("credential_hash", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_sensor"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_sensor_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_sensor_tenant_id_name"),
        sa.CheckConstraint(f"type IN ({_SENSOR_TYPE})", name="sensor_type"),
        sa.CheckConstraint(f"status IN ({_SENSOR_STATUS})", name="sensor_status"),
    )
    op.create_index("ix_sensor_tenant_id", "sensor", ["tenant_id"])
    op.create_index("ix_sensor_tenant_id_status", "sensor", ["tenant_id", "status"])

    # ---- audit_log ---------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_audit_log_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("hash", name="uq_audit_log_hash"),
        sa.CheckConstraint(f"actor_type IN ({_ACTOR_TYPE})", name="audit_log_actor_type"),
        sa.CheckConstraint(f"result IN ({_AUDIT_RESULT})", name="audit_log_result"),
        sa.CheckConstraint("hash ~ '^[0-9a-f]{64}$'", name="audit_log_hash_format"),
        sa.CheckConstraint(
            "prev_hash ~ '^[0-9a-f]{64}$'", name="audit_log_prev_hash_format"
        ),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.execute(
        "CREATE INDEX ix_audit_log_tenant_id_created_at ON audit_log (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_audit_log_actor_id_created_at ON audit_log (actor_id, created_at DESC)"
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    # audit_log is append-only. A trigger (not a REVOKE) enforces it, because a
    # REVOKE does not constrain the table owner.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sm_audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_immutable
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION sm_audit_log_immutable();
        """
    )

    # ---- updated_at triggers ---------------------------------------------
    for table in _TIMESTAMP_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_set_updated_at
            BEFORE UPDATE ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION sm_set_updated_at();
            """
        )


def downgrade() -> None:
    for table in _TIMESTAMP_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON "{table}"')
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS sm_audit_log_immutable()")

    op.drop_table("audit_log")
    op.drop_table("sensor")
    op.drop_table("role_permission")
    op.drop_table("user_role")
    op.drop_table("user")
    op.drop_table("role")
    op.drop_table("permission")
    op.drop_table("tenant")

    op.execute("DROP FUNCTION IF EXISTS sm_set_updated_at()")
