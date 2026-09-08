"""Phase 1 API request/response contracts (docs/CONTRACTS.md §1.2)."""

from __future__ import annotations

from .auth import LoginRequest, LoginResponse, LogoutResponse, MeResponse
from .health import DepStatus, HealthResponse, MetaResponse, ReadyResponse
from .pagination import CursorPage
from .users import CreateUserRequest, GrantRoleRequest, RoleSummary, UserResponse

__all__ = [
    "CreateUserRequest",
    "CursorPage",
    "DepStatus",
    "GrantRoleRequest",
    "HealthResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "MeResponse",
    "MetaResponse",
    "ReadyResponse",
    "RoleSummary",
    "UserResponse",
]
