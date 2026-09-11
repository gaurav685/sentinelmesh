"""Phase-12 authorization vocabulary: simulation:run, deception:manage.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-11

Notes
-----
- The `permission.code` CHECK constraint (`permission_code`, from `0001`) is a
  closed allow-list; a new code needs the constraint widened before the row
  can be inserted. `downgrade` restores the exact original list.
- Same seeding convention as `0002_seed_rbac.py`: `uuid5`-derived ids from the
  same namespace, so re-running against a fresh database is deterministic and
  `downgrade` deletes exactly what `upgrade` inserted.
- `read_only` is deliberately not granted either code — simulation and
  deception are operator actions, not passive observation.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_NAMESPACE = UUID("6f2a1c4e-9b3d-5a7f-8c1e-2d4b6a8f0c3e")

_OLD_PERMISSION_CODE = (
    "'users:read', 'users:create', 'users:update', "
    "'roles:read', 'roles:grant', "
    "'sensors:read', 'sensors:manage', "
    "'audit:read', 'ops:read', "
    "'detections:read', 'hunt:query', 'reports:generate', "
    "'response:execute', 'response:approve'"
)
_NEW_PERMISSION_CODE = _OLD_PERMISSION_CODE + ", 'simulation:run', 'deception:manage'"

PERMISSIONS: dict[str, str] = {
    "simulation:run": "Run a synthetic attack-scenario drill and view the digital twin / blast radius",
    "deception:manage": "Register, list, and tear down deception decoys; view captured interactions",
}

GRANTED_TO = ("platform_operator", "tenant_admin", "lead", "analyst")

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
