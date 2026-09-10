"""Defensive stress testing: which controls break which attack paths.

`apply_controls` produces a *new* twin with the controls applied; `stress_test`
compares the attack surface before and after. Deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .blast import AttackPath, attack_paths
from .model import TwinModel, TwinRelation

__all__ = ["DefensiveControl", "StressReport", "apply_controls", "stress_test"]

ControlKind = Literal["block_relation_kind", "isolate_asset", "harden_asset"]


@dataclass(frozen=True)
class DefensiveControl:
    kind: ControlKind
    #: For `block_relation_kind`: a `RelationKind` value. For `isolate_asset` /
    #: `harden_asset`: an asset id.
    target: str


def apply_controls(twin: TwinModel, controls: list[DefensiveControl]) -> TwinModel:
    blocked_kinds = {c.target for c in controls if c.kind == "block_relation_kind"}
    isolated = {c.target for c in controls if c.kind == "isolate_asset"}
    hardened = {c.target for c in controls if c.kind == "harden_asset"}

    relations: list[TwinRelation] = [
        r
        for r in twin.relations
        if r.kind.value not in blocked_kinds
        and r.src not in isolated
        and r.dst not in isolated
    ]
    weaknesses = [w for w in twin.weaknesses if w.asset_id not in hardened]
    return TwinModel(assets=twin.assets, relations=tuple(relations), weaknesses=tuple(weaknesses))


@dataclass(frozen=True)
class StressReport:
    paths_before: tuple[AttackPath, ...]
    paths_after: tuple[AttackPath, ...]
    #: Paths present before and gone after.
    paths_broken: tuple[AttackPath, ...]
    #: Feasibility of the best remaining path, [0, 1]. 0 = fully mitigated.
    residual_risk: float
    #: The single control that, applied alone, breaks the most paths.
    most_valuable_control: DefensiveControl | None


def stress_test(
    twin: TwinModel,
    *,
    sources: set[str],
    targets: set[str],
    controls: list[DefensiveControl],
    max_depth: int = 4,
) -> StressReport:
    before = attack_paths(twin, sources=sources, targets=targets, max_depth=max_depth)
    after = attack_paths(
        apply_controls(twin, controls), sources=sources, targets=targets, max_depth=max_depth
    )
    after_set = {(p.assets, p.relations) for p in after}
    broken = tuple(p for p in before if (p.assets, p.relations) not in after_set)
    residual = max((p.feasibility for p in after), default=0.0)

    best: DefensiveControl | None = None
    best_broken = -1
    for c in controls:
        solo_after = attack_paths(
            apply_controls(twin, [c]), sources=sources, targets=targets, max_depth=max_depth
        )
        solo_set = {(p.assets, p.relations) for p in solo_after}
        n = sum(1 for p in before if (p.assets, p.relations) not in solo_set)
        if n > best_broken:
            best_broken, best = n, c

    return StressReport(
        paths_before=before,
        paths_after=after,
        paths_broken=broken,
        residual_risk=round(residual, 6),
        most_valuable_control=best if best_broken > 0 else None,
    )
