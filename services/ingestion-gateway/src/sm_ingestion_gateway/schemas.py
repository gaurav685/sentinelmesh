"""Request / response shapes that are local to this service.

The event *envelope* is a platform contract (`sm_contracts`). These are just the
small HTTP wrappers the ingest endpoints return to a sensor.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from sm_contracts import SmBaseModel

__all__ = [
    "BatchIngestRequest",
    "BatchIngestResult",
    "IngestAccepted",
    "RejectedItem",
]


class IngestAccepted(SmBaseModel):
    """Response to `POST /api/v1/ingest/{source_type}`.

    `event_id` is null when the request was suppressed as a duplicate
    (`deduplicated = true`, HTTP 200).
    """

    event_id: UUID | None
    deduplicated: bool = False


class BatchIngestRequest(SmBaseModel):
    source_type: str = Field(min_length=1, max_length=32)
    events: list[dict[str, Any]] = Field(min_length=1)


class RejectedItem(SmBaseModel):
    index: int = Field(ge=0, description="Position in the submitted `events` array.")
    reason: str


class BatchIngestResult(SmBaseModel):
    accepted: int
    rejected: list[RejectedItem]
    event_ids: list[UUID]
