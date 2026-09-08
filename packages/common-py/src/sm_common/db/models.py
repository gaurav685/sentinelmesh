"""SQLAlchemy models for the Phase-1 control-plane tables.

These are the **database** models. They are never returned from an API — services
map them to the `sm_contracts` DTOs (Engineering Constitution §8). Security state
(`password_hash`, `failed_login_count`, `locked_until`, `credential_hash`, the
audit hash chain) exists only here.

Ownership: `api-gateway` is the only writer of every table in this module
(`docs/CONTRACTS.md §4`). `identity_link` belongs to `normalization-engine` and
arrives in Phase 2.

Enum-valued columns are `String` + a `CHECK` constraint rather than a native
Postgres enum: adding a value is then a one-line migration instead of an
`ALTER TYPE` that locks. The allowed values come from `sm_contracts` so the
contract and the schema cannot drift.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sm_contracts import (
    ActorType,
    AuditResult,
    PermissionCode,
    SensorStatus,
    SensorType,
    TenantStatus,
    UserStatus,
)

from ..ids import uuid7
from .base import Base, TimestampMixin

__all__ = [
    "AuditLog",
    "Permission",
    "Role",
    "RolePermission",
    "Sensor",
    "Tenant",
    "User",
    "UserRole",
]

def _in_values(column: str, enum_cls: type[StrEnum]) -> str:
    """Render `column IN (...)` from a contract enum, so the CHECK constraint and
    the contract cannot drift apart."""
    values = ", ".join(f"'{m.value}'" for m in enum_cls)
    return f"{column} IN ({values})"


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenant"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TenantStatus.active.value)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(_in_values("status", TenantStatus), name="tenant_status"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'", name="tenant_slug_format"),
        Index("ix_tenant_status", "status"),
    )


class User(TimestampMixin, Base):
    __tablename__ = "user"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=False
    )
    # Stored lower-cased by the application so `(tenant_id, email)` is a true
    # case-insensitive uniqueness constraint without the citext extension.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.invited.value)
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- security state: never serialized into a contract -------------------
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_id_email"),
        UniqueConstraint("tenant_id", "external_subject", name="uq_user_tenant_id_external_subject"),
        CheckConstraint(_in_values("status", UserStatus), name="user_status"),
        CheckConstraint("email = lower(email)", name="user_email_lowercase"),
        CheckConstraint("failed_login_count >= 0", name="user_failed_login_count_nonneg"),
        Index("ix_user_tenant_id_status", "tenant_id", "status"),
    )


class Role(TimestampMixin, Base):
    __tablename__ = "role"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    # NULL tenant_id marks a system role shared by every tenant.
    tenant_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    is_system: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    __table_args__ = (
        # Two partial unique indexes instead of one COALESCE expression: a role
        # name is unique among system roles, and unique within a tenant.
        Index(
            "uq_role_system_name",
            "name",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "uq_role_tenant_id_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(is_system AND tenant_id IS NULL) OR (NOT is_system AND tenant_id IS NOT NULL)",
            name="role_system_implies_no_tenant",
        ),
    )


class Permission(Base):
    __tablename__ = "permission"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (CheckConstraint(_in_values("code", PermissionCode), name="permission_code"),)


class UserRole(Base):
    __tablename__ = "user_role"

    user_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("role.id", ondelete="RESTRICT"), primary_key=True
    )
    granted_by: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_user_role_role_id", "role_id"),)


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("permission.id", ondelete="RESTRICT"), primary_key=True
    )

    __table_args__ = (Index("ix_role_permission_permission_id", "permission_id"),)


class Sensor(TimestampMixin, Base):
    __tablename__ = "sensor"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SensorStatus.pending.value)
    # Argon2id hash of the sensor credential. The credential itself is shown once
    # at registration and never stored.
    credential_hash: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_sensor_tenant_id_name"),
        CheckConstraint(_in_values("type", SensorType), name="sensor_type"),
        CheckConstraint(_in_values("status", SensorStatus), name="sensor_status"),
        Index("ix_sensor_tenant_id_status", "tenant_id", "status"),
    )


class AuditLog(Base):
    """Append-only. The application role is granted INSERT and SELECT only
    (migration 0001); UPDATE and DELETE are revoked so the chain cannot be
    rewritten in place."""

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7)
    # NULL for platform-level (cross-tenant) events.
    tenant_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(postgresql.UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[UUID | None] = mapped_column(postgresql.UUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[UUID | None] = mapped_column(postgresql.UUID(as_uuid=True), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # created_at is set by the application (not server_default) because it is an
    # input to the hash chain and must be known before INSERT.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(_in_values("actor_type", ActorType), name="audit_log_actor_type"),
        CheckConstraint(_in_values("result", AuditResult), name="audit_log_result"),
        CheckConstraint("hash ~ '^[0-9a-f]{64}$'", name="audit_log_hash_format"),
        CheckConstraint("prev_hash ~ '^[0-9a-f]{64}$'", name="audit_log_prev_hash_format"),
        UniqueConstraint("hash", name="uq_audit_log_hash"),
        Index("ix_audit_log_tenant_id_created_at", "tenant_id", text("created_at DESC")),
        Index("ix_audit_log_actor_id_created_at", "actor_id", text("created_at DESC")),
        Index("ix_audit_log_action", "action"),
    )
