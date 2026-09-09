from __future__ import annotations

import uuid

from sm_mitre_service.mapping import MappingEngine

from sm_contracts import MappingConfidence, MappingSource, MappingSubjectType

from .conftest import FakeCatalog, FakeMappingDb


async def test_known_ids_are_enriched_unknown_ids_are_unmapped(
    mapping_engine: tuple[MappingEngine, FakeMappingDb],
) -> None:
    engine, _ = mapping_engine
    result = await engine.map_techniques(
        ["T1110", "T1021", "T404", "T1110"], rationale="test",
    )
    assert result.matrix_version == "test-1"
    assert [m.technique_id for m in result.matches] == ["T1110", "T1021"]  # deduped
    assert result.unmapped == ["T404"]
    m = result.matches[0]
    assert m.name == "Brute Force"
    assert m.tactic_id == "TA0006" and m.tactic_name == "Credential Access"
    assert m.source is MappingSource.rule and m.confidence is MappingConfidence.medium


async def test_deprecated_technique_is_unmapped(
    mapping_engine: tuple[MappingEngine, FakeMappingDb],
) -> None:
    engine, _ = mapping_engine
    result = await engine.map_techniques(["T9999"], rationale="test")
    assert result.matches == []
    assert result.unmapped == ["T9999"]


async def test_no_catalog_marks_everything_unmapped() -> None:
    engine = MappingEngine(FakeCatalog(imported=False), FakeMappingDb())  # type: ignore[arg-type]
    result = await engine.map_techniques(["T1110", "T1021"], rationale="test")
    assert result.matrix_version is None
    assert result.matches == []
    assert result.unmapped == ["T1110", "T1021"]


async def test_persist_writes_one_statement_per_match(
    mapping_engine: tuple[MappingEngine, FakeMappingDb],
) -> None:
    engine, db = mapping_engine
    result = await engine.map_techniques(["T1110", "T1021"], rationale="r")
    n = await engine.persist(
        tenant_id=uuid.uuid4(), subject_type=MappingSubjectType.detection,
        subject_id=uuid.uuid4(), result=result,
    )
    assert n == 2
    assert len(db.executed) == 2


async def test_persist_is_a_noop_with_no_matches(
    mapping_engine: tuple[MappingEngine, FakeMappingDb],
) -> None:
    engine, db = mapping_engine
    result = await engine.map_techniques(["T404"], rationale="r")
    assert await engine.persist(
        tenant_id=uuid.uuid4(), subject_type=MappingSubjectType.detection,
        subject_id=uuid.uuid4(), result=result,
    ) == 0
    assert db.executed == []
