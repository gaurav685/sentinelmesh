"""Canonical entity contracts (safe DTOs).

These are the shapes services and the API exchange. They are deliberately **not**
the database models — no `password_hash`, no `failed_login_count`, no hash-chain
columns appear here (Engineering Constitution §8: never expose database models).
"""

from __future__ import annotations

from .audit import AuditRecord
from .detection import Anomaly, Detection, SecurityAlert, ThreatScore
from .rbac import Permission, Role, RolePermission, UserRoleGrant
from .sensor import Sensor
from .tenant import Tenant
from .user import User

__all__ = [
    "Anomaly",
    "AuditRecord",
    "Detection",
    "Permission",
    "Role",
    "RolePermission",
    "SecurityAlert",
    "Sensor",
    "Tenant",
    "ThreatScore",
    "User",
    "UserRoleGrant",
]
