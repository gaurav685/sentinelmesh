"""threat-intel-service API models (DRAFT — Phase 6, service-local)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from sm_contracts import (
    EnrichmentMatch,
    IndicatorType,
    ThreatIndicator,
    TiConfidence,
    TiUpdateAction,
)

__all__ = [
    "EnrichItem",
    "EnrichRequest",
    "EnrichResponse",
    "IndicatorsResponse",
    "SubmitIndicatorRequest",
    "SubmitIndicatorResponse",
]


class EnrichItem(BaseModel):
    type: IndicatorType
    value: str = Field(min_length=1, max_length=2048)


class EnrichRequest(BaseModel):
    items: list[EnrichItem] = Field(min_length=1, max_length=100)


class EnrichResponse(BaseModel):
    results: list[EnrichmentMatch]


class IndicatorsResponse(BaseModel):
    count: int
    indicators: list[ThreatIndicator]


class SubmitIndicatorRequest(BaseModel):
    type: IndicatorType
    value: str = Field(min_length=1, max_length=2048)
    confidence: TiConfidence = TiConfidence.medium
    tags: list[str] = Field(default_factory=list, max_length=32)
    actor_id: str | None = Field(default=None, max_length=64)
    reference: str = Field(default="", max_length=512)
    expires_at: datetime | None = None


class SubmitIndicatorResponse(BaseModel):
    indicator: ThreatIndicator
    action: TiUpdateAction
