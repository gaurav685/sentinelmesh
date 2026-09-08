from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from ..common import TenantScoped, TimestampedModel, to_utc
from ..enums import UserStatus

__all__ = ["User"]


class User(TimestampedModel, TenantScoped):
    """Safe user DTO.

    Security state (`password_hash`, `failed_login_count`, `locked_until`) lives
    only in the api-gateway database model and is never serialized in a contract.
    """

    id: UUID
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    status: UserStatus
    external_subject: str | None = Field(
        default=None,
        max_length=255,
        description="OIDC `sub` for federated users; null for local-only users.",
    )
    last_login_at: datetime | None = None

    @field_validator("last_login_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)
