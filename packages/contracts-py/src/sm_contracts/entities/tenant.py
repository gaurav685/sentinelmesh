from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from ..common import TimestampedModel
from ..enums import TenantStatus

__all__ = ["Tenant"]


class Tenant(TimestampedModel):
    """An isolated customer organization — the root of all data scoping.

    `Tenant` itself is not tenant-scoped.
    """

    id: UUID
    slug: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$",
        description="URL-safe stable identifier, unique across the platform (3-40 chars, no leading/trailing hyphen).",
    )
    name: str = Field(min_length=1, max_length=200)
    status: TenantStatus
    settings: dict[str, Any] = Field(default_factory=dict)
