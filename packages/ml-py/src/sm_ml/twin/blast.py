"""Attack-path enumeration and blast-radius analysis over a `TwinModel`.

Deterministic: bounded traversal, sorted output. No randomness, no clock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .model import RelationKind, TwinModel

__all__ = ["AttackPath", "BlastRadiusReport", "attack_paths", "blast_radius"]

_MAX_PATHS = 200


@dataclass(frozen=True)
class AttackPath:
    assets: tuple[str, ...]
    relations: tuple[RelationKind, ...]
    #: Product of the relation weights along the path, [0, 1]. Higher = easier.
    feasibility: float

    @property
    def hops(self) -> int:
        return len(self.relations)


def attack_paths(
    twin: TwinModel,
    *,
    sources: set[str],
    targets: set[str],
    max_depth: int = 4,
    max_paths: int = _MAX_PATHS,
) -> tuple[AttackPath, ...]:
    """Every simple path from a source asset to a target asset, up to
    `max_depth` hops. Deterministic order (by feasibility desc, then assets)."""
    depth = max(1, min(int(max_depth), 12))
    src_ids = sorted(s for s in sources if twin.asset(s) is not None)
    found: list[AttackPath] = []

    for start in src_ids:
        stack: list[tuple[str, tuple[str, ...], tuple[RelationKind, ...], float]] = [
            (start, (start,), (), 1.0)
        ]
        while stack and len(found) < max_paths:
            node, path, rels, feas = stack.pop()
            if node in targets and len(path) > 1:
                found.append(AttackPath(assets=path, relations=rels, feasibility=round(feas, 6)))
                continue
            if len(rels) >= depth:
                continue
            for r in sorted(
                twin.out_relations(node), key=lambda x: (x.dst, x.kind.value), reverse=True
            ):
                if r.dst in path:  # simple paths only
                    continue
                stack.append(
                    (r.dst, (*path, r.dst), (*rels, r.kind), feas * max(r.weight, 0.01))
                )

    found.sort(key=lambda p: (-p.feasibility, p.assets))
    return tuple(found[:max_paths])


@dataclass(frozen=True)
class BlastRadiusReport:
    seeds: tuple[str, ...]
    reached: tuple[str, ...]
    #: `asset_id -> minimum hop count from a seed`.
    hop_of: dict[str, int]
    critical_reached: tuple[str, ...]
    #: Fraction of the twin's total criticality that the reached set represents,
    #: [0, 1]. The headline number.
    score: float
    #: Weaknesses on reached assets that would amplify further spread.
    amplifying_weaknesses: tuple[str, ...] = field(default_factory=tuple)


def blast_radius(
    twin: TwinModel,
    *,
    seeds: set[str],
    max_hops: int = 4,
    min_weight: float = 0.0,
) -> BlastRadiusReport:
    """What an attacker who holds `seeds` can reach within `max_hops`, and how
    much of the estate's value that represents."""
    hops = max(1, min(int(max_hops), 12))
    seed_ids = sorted(s for s in seeds if twin.asset(s) is not None)

    hop_of: dict[str, int] = {s: 0 for s in seed_ids}
    q: deque[str] = deque(seed_ids)
    while q:
        node = q.popleft()
        if hop_of[node] >= hops:
            continue
        for r in sorted(twin.out_relations(node), key=lambda x: (x.dst, x.kind.value)):
            if r.weight < min_weight:
                continue
            if r.dst not in hop_of:
                hop_of[r.dst] = hop_of[node] + 1
                q.append(r.dst)

    reached = tuple(sorted(hop_of))
    reached_assets = [a for a in (twin.asset(x) for x in reached) if a is not None]
    total_crit = sum(a.criticality for a in twin.assets) or 1.0
    reached_crit = sum(a.criticality for a in reached_assets)
    critical = tuple(a.id for a in reached_assets if a.criticality >= 0.8)
    amplifiers = tuple(
        sorted(
            {
                f"{w.asset_id}:{w.kind.value}"
                for a in reached
                for w in twin.weaknesses_of(a)
                if w.severity_rank >= 2
            }
        )
    )
    return BlastRadiusReport(
        seeds=tuple(seed_ids),
        reached=reached,
        hop_of=hop_of,
        critical_reached=critical,
        score=round(reached_crit / total_crit, 6),
        amplifying_weaknesses=amplifiers,
    )
