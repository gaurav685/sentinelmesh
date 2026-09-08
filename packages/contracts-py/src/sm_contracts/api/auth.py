from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field, SecretStr, field_validator

from ..common import SmBaseModel, to_utc
from ..entities import Tenant, User
from ..enums import PermissionCode

__all__ = ["LoginRequest", "LoginResponse", "LogoutResponse", "MeResponse"]


class LoginRequest(SmBaseModel):
    """Local fallback login. Federated users authenticate via OIDC instead.

    `tenant_slug` disambiguates the account; the server still resolves the tenant
    server-side and never trusts a tenant id from the client.
    """

    tenant_slug: str = Field(min_length=1, max_length=40)
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(SmBaseModel):
    user: User
    permissions: list[PermissionCode] = Field(
        description="Effective permissions for this session, resolved server-side."
    )
    session_expires_at: datetime

    @field_validator("session_expires_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class LogoutResponse(SmBaseModel):
    ok: bool = True


class MeResponse(SmBaseModel):
    user: User
    tenant: Tenant
    roles: list[str] = Field(description="Role names granted to the user.")
    permissions: list[PermissionCode]
