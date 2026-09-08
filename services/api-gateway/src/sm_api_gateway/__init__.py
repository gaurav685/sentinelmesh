"""SentinelMesh API gateway (BFF).

The frontend's only backend. Owns authentication, deny-by-default RBAC,
tenant-scoped reads and the audit trail for user-facing actions.
"""

from __future__ import annotations

from .app import build_services, create_app
from .version import API_PREFIX, API_VERSION, SERVICE_NAME, SERVICE_VERSION

__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "build_services",
    "create_app",
]
