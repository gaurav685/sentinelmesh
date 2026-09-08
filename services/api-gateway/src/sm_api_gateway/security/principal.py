"""The authenticated principal.

Built server-side on every request from the session record plus a fresh database
read of the user's roles and permissions. Nothing here is taken from request
data: not the user id, not the tenant id, not a role, not a permission
(Engineering Constitution §5, §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sm_contracts import PermissionCode

__all__ = ["Principal"]


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    email: str
    session_id: str
    csrf_token: str
    roles: frozenset[str]
    permissions: frozenset[str]

    def has(self, permission: PermissionCode | str) -> bool:
        code = permission.value if isinstance(permission, PermissionCode) else permission
        return code in self.permissions

    def permission_codes(self) -> list[PermissionCode]:
        """Permissions as contract enum members, sorted. Unknown codes (a
        database row from a newer deployment) are skipped rather than crashing
        the response."""
        known = {c.value: c for c in PermissionCode}
        return [known[code] for code in sorted(self.permissions) if code in known]
