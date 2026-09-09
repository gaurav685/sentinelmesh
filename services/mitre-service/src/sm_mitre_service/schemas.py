"""mitre-service API models (DRAFT — Phase 6, service-local)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from sm_contracts import (
    AttackMatrixVersion,
    AttackTechnique,
    MappingConfidence,
    MappingSource,
    MappingSubjectType,
    TechniqueMatch,
)

__all__ = [
    "HeatmapCellModel",
    "HeatmapResponse",
    "MapRequest",
    "MapResponse",
    "TechniquesResponse",
]


class TechniquesResponse(BaseModel):
    matrix: AttackMatrixVersion | None
    count: int
    techniques: list[AttackTechnique]


class MapRequest(BaseModel):
    subject_type: MappingSubjectType
    subject_id: UUID
    technique_ids: list[str] = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=1000)
    source: MappingSource = MappingSource.rule
    confidence: MappingConfidence = MappingConfidence.medium
    persist: bool = False


class MapResponse(BaseModel):
    matrix_version: str | None
    matches: list[TechniqueMatch]
    unmapped: list[str]
    persisted: int


class HeatmapCellModel(BaseModel):
    technique_id: str
    name: str
    tactic_id: str | None
    subject_count: int


class HeatmapResponse(BaseModel):
    matrix_version: str | None
    cells: list[HeatmapCellModel]
