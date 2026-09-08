"""Tenant-scoped repositories."""

from __future__ import annotations

from .protocols import RoleRepository, TenantRepository, UserRepository
from .sql import SqlRoleRepository, SqlTenantRepository, SqlUserRepository

__all__ = [
    "RoleRepository",
    "SqlRoleRepository",
    "SqlTenantRepository",
    "SqlUserRepository",
    "TenantRepository",
    "UserRepository",
]
