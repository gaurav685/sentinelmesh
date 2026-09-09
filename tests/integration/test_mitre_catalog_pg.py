"""Phase 6 Unit 2 — real PostgreSQL: catalog import + technique mapping.

Imports the labelled FIXTURE bundle (`tests/fixtures/attack_mini_bundle.json` —
NOT real ATT&CK data), then exercises `MappingEngine` and the heatmap.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sm_mitre_service.catalog import CatalogRepository
from sm_mitre_service.mapping import MappingEngine
from sm_mitre_service.stix import bundle_sha256, parse_stix_bundle
from sqlalchemy import text

from sm_common.db import Database
from sm_contracts import MappingSubjectType

pytestmark = pytest.mark.integration

_BUNDLE = Path(__file__).resolve().parents[1] / "fixtures" / "attack_mini_bundle.json"


async def _tenant(db: Database) -> uuid.UUID:
    tid = uuid.uuid4()
    async with db.transaction() as s:
        await s.execute(
            text("INSERT INTO tenant (id, slug, name, status) VALUES (:id, :slug, 'T', 'active')"),
            {"id": tid, "slug": f"t-{tid.hex[:12]}"},
        )
    return tid


@pytest.fixture
async def imported(clean: Database) -> tuple[CatalogRepository, MappingEngine]:
    raw = _BUNDLE.read_bytes()
    parsed = parse_stix_bundle(raw, version="fixture-1", source="fixture")
    catalog = CatalogRepository(clean)
    await catalog.import_catalog(parsed, bundle_sha256=bundle_sha256(raw))
    return catalog, MappingEngine(catalog, clean)


async def test_import_records_the_matrix_version(
    imported: tuple[CatalogRepository, MappingEngine],
) -> None:
    catalog, _ = imported
    version = await catalog.latest_version()
    assert version is not None
    assert version.version == "fixture-1"
    assert version.technique_count == 3  # T9999 is a technique but deprecated -> still counted
    assert version.subtechnique_count == 1
    assert len(version.stix_bundle_sha256) == 64


async def test_deprecated_techniques_are_hidden_from_the_listing(
    imported: tuple[CatalogRepository, MappingEngine],
) -> None:
    catalog, _ = imported
    live = {t.technique_id for t in await catalog.list_techniques()}
    assert live == {"T1110", "T1110.001", "T1021"}
    assert "T9999" in {t.technique_id for t in await catalog.list_techniques(include_deprecated=True)}


async def test_reimport_replaces_in_place(
    imported: tuple[CatalogRepository, MappingEngine], clean: Database
) -> None:
    catalog, _ = imported
    raw = _BUNDLE.read_bytes()
    await catalog.import_catalog(parse_stix_bundle(raw, version="fixture-1"), bundle_sha256=bundle_sha256(raw))
    assert await catalog.technique_count() == 4  # not doubled


async def test_map_and_persist_and_heatmap(
    imported: tuple[CatalogRepository, MappingEngine], clean: Database
) -> None:
    _, engine = imported
    tenant = await _tenant(clean)
    subject = uuid.uuid4()

    result = await engine.map_techniques(["T1110", "T1021", "T404", "T9999"], rationale="rule fired")
    assert [m.technique_id for m in result.matches] == ["T1110", "T1021"]
    assert sorted(result.unmapped) == ["T404", "T9999"]

    n = await engine.persist(
        tenant_id=tenant, subject_type=MappingSubjectType.detection, subject_id=subject, result=result,
    )
    assert n == 2
    # re-persist is an upsert, not a duplicate
    await engine.persist(
        tenant_id=tenant, subject_type=MappingSubjectType.detection, subject_id=subject, result=result,
    )

    cells = await engine.heatmap(tenant)
    assert {c.technique_id: c.subject_count for c in cells} == {"T1110": 1, "T1021": 1}
    assert next(c for c in cells if c.technique_id == "T1110").name == "Brute Force"

    # another tenant's heatmap is empty
    assert await engine.heatmap(await _tenant(clean)) == []
