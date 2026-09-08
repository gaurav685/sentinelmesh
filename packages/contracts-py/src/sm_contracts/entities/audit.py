from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc
from ..enums import ActorType, AuditResult

__all__ = ["AuditRecord"]


class AuditRecord(SmBaseModel):
    """Append-only audit entry (safe DTO).

    The storage row additionally carries per-tenant hash-chain columns
    (`prev_hash`, `hash`) which are an integrity mechanism, not part of the
    contract.
    """

    id: UUID
    tenant_id: UUID | None = Field(
        default=None, description="Null for platform-level (cross-tenant) events."
    )
    actor_type: ActorType
    actor_id: UUID | None = None
    action: str = Field(min_length=1, max_length=128)
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, max_length=128)
    result: AuditResult
    request_id: UUID | None = None
    correlation_id: UUID | None = None
    ip: str | None = Field(default=None, max_length=45, description="IPv4/IPv6 textual form.")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)
