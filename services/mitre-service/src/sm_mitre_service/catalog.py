"""Postgres catalog store: tactics, techniques, matrix versions.

An import replaces the whole catalog for a version in one transaction. Reads are
global (the catalog is not tenant-scoped). An unknown technique id is a miss, not
a guess.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from sm_common.db import (
    AttackMatrixVersionRow,
    AttackTacticRow,
    AttackTechniqueRow,
    Database,
)
from sm_contracts import AttackMatrixVersion, AttackTechnique

from .stix import ParsedCatalog

__all__ = ["CatalogRepository"]


class CatalogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def import_catalog(self, parsed: ParsedCatalog, *, bundle_sha256: str) -> AttackMatrixVersion:
        now = datetime.now(UTC)
        async with self._db.transaction() as s:
            await s.execute(
                delete(AttackTechniqueRow).where(AttackTechniqueRow.matrix_version == parsed.version)
            )
            await s.execute(
                delete(AttackTacticRow).where(AttackTacticRow.matrix_version == parsed.version)
            )
            for t in parsed.tactics:
                s.add(AttackTacticRow(
                    tactic_id=t.tactic_id, name=t.name, shortname=t.shortname,
                    description=t.description, matrix_version=t.matrix_version,
                ))
            for tech in parsed.techniques:
                s.add(AttackTechniqueRow(
                    technique_id=tech.technique_id, name=tech.name, tactic_ids=tech.tactic_ids,
                    description=tech.description, is_subtechnique=tech.is_subtechnique,
                    parent_technique_id=tech.parent_technique_id,
                    matrix_version=tech.matrix_version, deprecated=tech.deprecated,
                ))
            stmt = insert(AttackMatrixVersionRow).values(
                version=parsed.version, source=parsed.source, imported_at=now,
                tactic_count=len(parsed.tactics),
                technique_count=sum(1 for x in parsed.techniques if not x.is_subtechnique),
                subtechnique_count=parsed.subtechnique_count,
                stix_bundle_sha256=bundle_sha256,
            ).on_conflict_do_update(
                index_elements=[AttackMatrixVersionRow.version],
                set_={
                    "source": parsed.source, "imported_at": now,
                    "tactic_count": len(parsed.tactics),
                    "technique_count": sum(1 for x in parsed.techniques if not x.is_subtechnique),
                    "subtechnique_count": parsed.subtechnique_count,
                    "stix_bundle_sha256": bundle_sha256,
                },
            )
            await s.execute(stmt)
        return AttackMatrixVersion(
            version=parsed.version, source=parsed.source, imported_at=now,
            tactic_count=len(parsed.tactics),
            technique_count=sum(1 for x in parsed.techniques if not x.is_subtechnique),
            subtechnique_count=parsed.subtechnique_count, stix_bundle_sha256=bundle_sha256,
        )

    async def latest_version(self) -> AttackMatrixVersion | None:
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(AttackMatrixVersionRow).order_by(AttackMatrixVersionRow.imported_at.desc())
                )
            ).scalars().first()
        if row is None:
            return None
        return AttackMatrixVersion(
            version=row.version, source=row.source, imported_at=row.imported_at,
            tactic_count=row.tactic_count, technique_count=row.technique_count,
            subtechnique_count=row.subtechnique_count, stix_bundle_sha256=row.stix_bundle_sha256,
        )

    async def technique_count(self) -> int:
        async with self._db.transaction() as s:
            return int((await s.execute(select(func.count()).select_from(AttackTechniqueRow))).scalar_one())

    async def get_technique(self, technique_id: str) -> AttackTechnique | None:
        async with self._db.transaction() as s:
            row = await s.get(AttackTechniqueRow, technique_id)
        if row is None:
            return None
        return AttackTechnique(
            technique_id=row.technique_id, name=row.name, tactic_ids=list(row.tactic_ids),
            description=row.description, is_subtechnique=row.is_subtechnique,
            parent_technique_id=row.parent_technique_id, matrix_version=row.matrix_version,
            deprecated=row.deprecated,
        )

    async def list_techniques(self, *, include_deprecated: bool = False) -> list[AttackTechnique]:
        async with self._db.transaction() as s:
            stmt = select(AttackTechniqueRow).order_by(AttackTechniqueRow.technique_id)
            if not include_deprecated:
                stmt = stmt.where(AttackTechniqueRow.deprecated.is_(False))
            rows = (await s.execute(stmt)).scalars().all()
        return [
            AttackTechnique(
                technique_id=r.technique_id, name=r.name, tactic_ids=list(r.tactic_ids),
                description=r.description, is_subtechnique=r.is_subtechnique,
                parent_technique_id=r.parent_technique_id, matrix_version=r.matrix_version,
                deprecated=r.deprecated,
            )
            for r in rows
        ]

    async def tactic_names(self) -> dict[str, str]:
        async with self._db.transaction() as s:
            rows = (await s.execute(select(AttackTacticRow.tactic_id, AttackTacticRow.name))).all()
        return {tid: name for tid, name in rows}
