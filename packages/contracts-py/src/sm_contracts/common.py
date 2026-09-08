"""Shared base models and field types for all SentinelMesh contracts.

Design rules enforced here (Engineering Constitution §7, §8):
- Every contract model forbids unknown fields (`extra="forbid"`) — this is the
  primary mass-assignment defense for request models and keeps event/entity
  payloads strict.
- Datetimes are timezone-aware and normalized to UTC at validation time.
- Identifiers are `uuid.UUID` everywhere (never bare strings).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = [
    "UUID",
    "SmBaseModel",
    "TenantScoped",
    "TimestampedModel",
    "to_utc",
]


def to_utc(value: datetime) -> datetime:
    """Return `value` as a timezone-aware UTC datetime.

    A naive datetime is rejected — callers must be explicit about timezone so we
    never silently assume local time for security-relevant timestamps.
    """
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class SmBaseModel(BaseModel):
    """Base for every contract model."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class TimestampedModel(SmBaseModel):
    """Mixin for persisted entities exposed over a contract."""

    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _tz_aware_utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class TenantScoped(SmBaseModel):
    """Mixin marking a model as belonging to exactly one tenant.

    `tenant_id` in a contract is informational for the consumer; it is NEVER the
    source of authorization scoping. Server-side code derives the tenant from the
    authenticated principal and must not trust a client-supplied value
    (Engineering Constitution §6).
    """

    tenant_id: UUID
