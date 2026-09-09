"""Seed the permission catalog, the system roles, and their grants.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-08

Notes
-----
- Ids are derived with `uuid5` from a fixed namespace, so re-running against a
  fresh database produces the same ids and `downgrade` can delete exactly what
  `upgrade` inserted.
- The permission set is the authorization vocabulary. Deny-by-default means a
  role holds only what is granted here; nothing is implied.
- Later phases add their own permissions in their own migrations; this one owns
  only the Phase-1 vocabulary.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_NAMESPACE = UUID("6f2a1c4e-9b3d-5a7f-8c1e-2d4b6a8f0c3e")


def _permission_id(code: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"permission:{code}")


def _role_id(name: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"role:{name}")


# code -> human description. `resource_type` and `action` are split from the code.
PERMISSIONS: dict[str, str] = {
    "users:read": "List and view users within the caller's tenant",
    "users:create": "Invite or create a user within the caller's tenant",
    "users:update": "Modify a user within the caller's tenant",
    "roles:read": "List roles available to the caller's tenant",
    "roles:grant": "Grant or revoke a role for a user",
    "sensors:read": "List and view telemetry sensors",
    "sensors:manage": "Register, rotate, or disable a telemetry sensor",
    "audit:read": "Read the tenant audit log",
    "ops:read": "Read operational dependency health detail",
    "detections:read": "List and view detections",
    "hunt:query": "Run threat-hunting queries against the graph",
    "reports:generate": "Generate reports",
    "response:execute": "Execute an autonomous response action",
    "response:approve": "Approve a pending response action",
}

ROLES: dict[str, str] = {
    "platform_operator": "SentinelMesh platform operator; cross-tenant, break-glass, fully audited",
    "tenant_admin": "Administers users, roles, and sensors within one tenant",
    "lead": "SOC lead; approves response actions and manages investigations",
    "analyst": "SOC analyst; investigates detections and hunts",
    "read_only": "Read-only observer",
}

GRANTS: dict[str, tuple[str, ...]] = {
    "platform_operator": tuple(PERMISSIONS),
    "tenant_admin": (
        "users:read",
        "users:create",
        "users:update",
        "roles:read",
        "roles:grant",
        "sensors:read",
        "sensors:manage",
        "audit:read",
        "detections:read",
        "hunt:query",
        "reports:generate",
        "response:approve",
    ),
    "lead": (
        "users:read",
        "roles:read",
        "sensors:read",
        "audit:read",
        "detections:read",
        "hunt:query",
        "reports:generate",
        "response:approve",
    ),
    "analyst": (
        "sensors:read",
        "detections:read",
        "hunt:query",
        "reports:generate",
    ),
    "read_only": (
        "sensors:read",
        "detections:read",
    ),
}


# Explicit column types: offline (`--sql`) rendering needs them to emit literal
# UUID/boolean values, and `downgrade` needs them to adapt UUID bind values.
_UUID_T = postgresql.UUID(as_uuid=True)

permission_table = sa.table(
    "permission",
    sa.column("id", _UUID_T),
    sa.column("code", sa.String),
    sa.column("description", sa.String),
    sa.column("resource_type", sa.String),
    sa.column("action", sa.String),
)
role_table = sa.table(
    "role",
    sa.column("id", _UUID_T),
    sa.column("tenant_id", _UUID_T),
    sa.column("name", sa.String),
    sa.column("description", sa.String),
    sa.column("is_system", sa.Boolean),
)
role_permission_table = sa.table(
    "role_permission", sa.column("role_id", _UUID_T), sa.column("permission_id", _UUID_T)
)


def upgrade() -> None:
    permission_rows = []
    for code, description in PERMISSIONS.items():
        resource_type, action = code.split(":", 1)
        permission_rows.append(
            {
                "id": _permission_id(code),
                "code": code,
                "description": description,
                "resource_type": resource_type,
                "action": action,
            }
        )

    role_rows = [
        {
            "id": _role_id(name),
            "tenant_id": None,
            "name": name,
            "description": description,
            "is_system": True,
        }
        for name, description in ROLES.items()
    ]

    grant_rows = [
        {"role_id": _role_id(role_name), "permission_id": _permission_id(code)}
        for role_name, codes in GRANTS.items()
        for code in codes
    ]

    op.bulk_insert(permission_table, permission_rows)
    op.bulk_insert(role_table, role_rows)
    op.bulk_insert(role_permission_table, grant_rows)


def downgrade() -> None:
    role_ids = [_role_id(name) for name in ROLES]
    permission_ids = [_permission_id(code) for code in PERMISSIONS]

    # Typed `IN` bindings: SQLAlchemy compiles an expanding parameter list per
    # dialect and adapts the UUID values from the column types above. The earlier
    # `ANY(:ids::uuid[])` text broke under asyncpg — `::` is an escaped colon, so
    # the cast was emitted as `$1:uuid[]`.
    op.execute(
        role_permission_table.delete().where(role_permission_table.c.role_id.in_(role_ids))
    )
    op.execute(role_table.delete().where(role_table.c.id.in_(role_ids)))
    op.execute(permission_table.delete().where(permission_table.c.id.in_(permission_ids)))
