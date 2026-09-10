"""Security digital twin (Phase 12).

    build_twin(assets, relations, weaknesses) -> TwinModel   (deterministic, frozen)
    attack_paths(twin, sources=, targets=, max_depth=)       -> tuple[AttackPath]
    blast_radius(twin, seeds=, max_hops=)                    -> BlastRadiusReport
    stress_test(twin, sources=, targets=, controls=)         -> StressReport

Standard-library and a pure function of its inputs. Scenario execution and
blast-radius analysis run against this model — never against real systems.
"""

from __future__ import annotations

from .blast import AttackPath, BlastRadiusReport, attack_paths, blast_radius
from .model import (
    AssetKind,
    RelationKind,
    TwinAsset,
    TwinModel,
    TwinRelation,
    TwinWeakness,
    WeaknessKind,
    build_twin,
)
from .stress import DefensiveControl, StressReport, apply_controls, stress_test

__all__ = [
    "AssetKind",
    "AttackPath",
    "BlastRadiusReport",
    "DefensiveControl",
    "RelationKind",
    "StressReport",
    "TwinAsset",
    "TwinModel",
    "TwinRelation",
    "TwinWeakness",
    "WeaknessKind",
    "apply_controls",
    "attack_paths",
    "blast_radius",
    "build_twin",
    "stress_test",
]
