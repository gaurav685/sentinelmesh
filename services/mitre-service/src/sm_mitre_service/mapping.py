"""Technique-mapping engine.

A mapping is a *validation + enrichment* of the candidate technique ids a
detection rule already named, against the imported catalog: unknown ids are
reported `unmapped` (never guessed), known ids get their name, tactic, and the
matrix version. An LLM-assisted mapping (`MappingSource.llm`) is allowed via the
`/map` API but is never produced here automatically and is never authoritative
alone (ADR-014).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from sm_common.db import AttackTechniqueRow, Database, TechniqueMappingRow
from sm_common.ids import uuid7
from sm_contracts import (
    EvidenceItem,
    MappingConfidence,
    MappingSource,
    MappingSubjectType,
    TechniqueMatch,
)

from .catalog import CatalogRepository

__all__ = ["HeatmapCell", "MappingEngine", "MappingResult"]


@dataclass(frozen=True)
class MappingResult:
    matrix_version: str | None
    matches: list[TechniqueMatch]
    unmapped: list[str]


@dataclass(frozen=True)
class HeatmapCell:
    technique_id: str
    name: str
    tactic_id: str | None
    subject_count: int


class MappingEngine:
    def __init__(self, catalog: CatalogRepository, db: Database) -> None:
        self._catalog = catalog
        self._db = db

    async def map_techniques(
        self,
        technique_ids: list[str],
        *,
        rationale: str,
        source: MappingSource = MappingSource.rule,
        confidence: MappingConfidence = MappingConfidence.medium,
    ) -> MappingResult:
        version = await self._catalog.latest_version()
        if version is None:
            return MappingResult(matrix_version=None, matches=[], unmapped=list(dict.fromkeys(technique_ids)))
        tactic_names = await self._catalog.tactic_names()
        matches: list[TechniqueMatch] = []
        unmapped: list[str] = []
        for tid in dict.fromkeys(technique_ids):  # dedupe, preserve order
            tech = await self._catalog.get_technique(tid)
            if tech is None or tech.deprecated:
                unmapped.append(tid)
                continue
            tactic_id = tech.tactic_ids[0] if tech.tactic_ids else None
            matches.append(TechniqueMatch(
                technique_id=tid, name=tech.name, tactic_id=tactic_id,
                tactic_name=tactic_names.get(tactic_id) if tactic_id else None,
                confidence=confidence, source=source, rationale=rationale,
                matrix_version=version.version,
            ))
        return MappingResult(matrix_version=version.version, matches=matches, unmapped=unmapped)

    async def persist(
        self,
        *,
        tenant_id: UUID,
        subject_type: MappingSubjectType,
        subject_id: UUID,
        result: MappingResult,
        evidence: list[EvidenceItem] | None = None,
    ) -> int:
        if not result.matches:
            return 0
        ev = [e.model_dump(mode="json") for e in (evidence or [])]
        async with self._db.transaction() as s:
            for m in result.matches:
                stmt = insert(TechniqueMappingRow).values(
                    id=uuid7(), tenant_id=tenant_id, subject_type=subject_type.value,
                    subject_id=subject_id, technique_id=m.technique_id, tactic_id=m.tactic_id,
                    confidence=m.confidence.value, source=m.source.value, rationale=m.rationale,
                    evidence=ev, matrix_version=m.matrix_version,
                ).on_conflict_do_update(
                    constraint="uq_technique_mapping_subject_technique_source",
                    set_={
                        "tactic_id": m.tactic_id, "confidence": m.confidence.value,
                        "rationale": m.rationale, "evidence": ev,
                        "matrix_version": m.matrix_version,
                    },
                )
                await s.execute(stmt)
        return len(result.matches)

    async def heatmap(self, tenant_id: UUID) -> list[HeatmapCell]:
        distinct = func.count(func.distinct(TechniqueMappingRow.subject_id)).label("n")
        stmt = (
            select(
                TechniqueMappingRow.technique_id,
                TechniqueMappingRow.tactic_id,
                AttackTechniqueRow.name,
                distinct,
            )
            .join(
                AttackTechniqueRow,
                AttackTechniqueRow.technique_id == TechniqueMappingRow.technique_id,
                isouter=True,
            )
            .where(TechniqueMappingRow.tenant_id == tenant_id)
            .group_by(
                TechniqueMappingRow.technique_id,
                TechniqueMappingRow.tactic_id,
                AttackTechniqueRow.name,
            )
            .order_by(distinct.desc())
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).all()
        return [
            HeatmapCell(technique_id=tid, name=name or tid, tactic_id=tac, subject_count=int(n))
            for tid, tac, name, n in rows
        ]
