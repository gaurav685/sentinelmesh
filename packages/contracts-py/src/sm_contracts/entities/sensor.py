from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from ..common import TenantScoped, TimestampedModel, to_utc
from ..enums import SensorStatus, SensorType

__all__ = ["Sensor"]


class Sensor(TenantScoped, TimestampedModel):
    """A machine identity that emits telemetry for exactly one tenant.

    The sensor's `tenant_id` is authoritative for every event it produces; the
    ingestion path overwrites any tenant value in an inbound payload with this
    (Engineering Constitution §6).
    """

    id: UUID
    name: str = Field(min_length=1, max_length=128)
    type: SensorType
    status: SensorStatus
    last_seen_at: datetime | None = None

    @field_validator("last_seen_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)
