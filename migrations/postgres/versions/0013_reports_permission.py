"""Phase-14 authorization vocabulary: reports:read.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-12

Notes
-----
- The `permission.code` CHECK constraint is a closed allow-list; a new
  code needs it widened again before the row can be inserted.
  `downgrade` restores the exact 0010-era list.
- `reports:generate` (the write side) has existed since `0001`/`0002` as
  a placeholder, seeded but until now unenforced by any route. This
  migration only adds its read counterpart — `reports:generate`'s own
  seed row and grants are untouched.
- Same seeding convention as `0002_seed_rbac.py` / `0008` / `0010`:
  `uuid5`-derived ids from the same namespace, deterministic, and
  `downgrade` deletes exactly what `upgrade` inserted.
- Viewing a report is a read-only analytical action, same tier as
  `memory:read` (Phase 13) — granted to every role including
  `read_only`. Role-gating a *compliance* report to `lead`/`tenant_admin`
  (R22) happens in `api-gateway`'s route code on `kind == "compliance"`,
  not via a second permission code — the distinction is by report
  content, not by a different capability.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_NAMESPACE = UUID("6f2a1c4e-9b3d-5a7f-8c1e-2d4b6a8f0c3e")

_OLD_PERMISSION_CODE = (
    "'users:read', 'users:create', 'users:update', "
    "'roles:read', 'roles:grant', "
    "'sensors:read', 'sensors:manage', "
    "'audit:read', 'ops:read', "
    "'detections:read', 'hunt:query', 'reports:generate', "
    "'response:execute', 'response:approve', "
    "'simulation:run', 'deception:manage', "
    "'memory:read'"
)
_NEW_PERMISSION_CODE = _OLD_PERMISSION_CODE + ", 'reports:read'"

PERMISSIONS: dict[str, str] = {
    "reports:read": "View generated incident/executive/SOC/compliance reports",
}

GRANTED_TO = ("platform_operator", "tenant_admin", "lead", "analyst", "read_only")

_UUID_T = postgresql.UUID(as_uuid=True)


def _permission_id(code: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"permission:{code}")


def _role_id(name: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"role:{name}")


permission_table = sa.table(
    "permission",
    sa.column("id", _UUID_T),
    sa.column("code", sa.String),
    sa.column("description", sa.String),
    sa.column("resource_type", sa.String),
    sa.column("action", sa.String),
)
role_permission_table = sa.table(
    "role_permission", sa.column("role_id", _UUID_T), sa.column("permission_id", _UUID_T)
)


def upgrade() -> None:
    op.drop_constraint("permission_code", "permission", type_="check")
    op.create_check_constraint("permission_code", "permission", f"code IN ({_NEW_PERMISSION_CODE})")

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
    op.bulk_insert(permission_table, permission_rows)

    grant_rows = [
        {"role_id": _role_id(role_name), "permission_id": _permission_id(code)}
        for role_name in GRANTED_TO
        for code in PERMISSIONS
    ]
    op.bulk_insert(role_permission_table, grant_rows)


def downgrade() -> None:
    permission_ids = [_permission_id(code) for code in PERMISSIONS]
    role_ids = [_role_id(name) for name in GRANTED_TO]

    op.execute(
        role_permission_table.delete().where(
            role_permission_table.c.role_id.in_(role_ids),
            role_permission_table.c.permission_id.in_(permission_ids),
        )
    )
    op.execute(permission_table.delete().where(permission_table.c.id.in_(permission_ids)))

    op.drop_constraint("permission_code", "permission", type_="check")
    op.create_check_constraint("permission_code", "permission", f"code IN ({_OLD_PERMISSION_CODE})")
