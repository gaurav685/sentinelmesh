"""The security digital twin — a deterministic model of assets, relationships
and weaknesses (Phase 12).

Standard-library, frozen, and a pure function of its inputs. Scenario execution
and blast-radius analysis run against **this model**, never against real
systems. Everything is sorted on construction so any downstream computation is
reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "AssetKind",
    "RelationKind",
    "TwinAsset",
    "TwinModel",
    "TwinRelation",
    "TwinWeakness",
    "WeaknessKind",
    "build_twin",
]


class AssetKind(StrEnum):
    identity = "identity"
    host = "host"
    service = "service"
    network = "network"
    data_store = "data_store"
    credential = "credential"
    external = "external"


class RelationKind(StrEnum):
    runs_on = "runs_on"
    connects_to = "connects_to"
    authenticates_to = "authenticates_to"
    depends_on = "depends_on"
    stores = "stores"
    grants_access = "grants_access"
    trusts = "trusts"
    exposes = "exposes"


class WeaknessKind(StrEnum):
    misconfiguration = "misconfiguration"
    unpatched_cve = "unpatched_cve"
    weak_credential = "weak_credential"
    excessive_privilege = "excessive_privilege"
    public_exposure = "public_exposure"
    missing_segmentation = "missing_segmentation"


_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class TwinAsset:
    id: str
    kind: AssetKind
    name: str = ""
    #: Business value, [0, 1]. Drives the blast-radius score.
    criticality: float = 0.5
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("asset id is required")
        if not 0.0 <= self.criticality <= 1.0:
            raise ValueError(f"criticality out of range: {self.criticality}")


@dataclass(frozen=True)
class TwinRelation:
    src: str
    dst: str
    kind: RelationKind
    #: Traversal ease, [0, 1]. 1 = an attacker crosses this trivially; lower =
    #: harder. Used to weight attack-path feasibility.
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.src == self.dst:
            raise ValueError("a relation cannot be a self-loop")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight out of range: {self.weight}")


@dataclass(frozen=True)
class TwinWeakness:
    asset_id: str
    kind: WeaknessKind
    severity: str = "medium"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITY_RANK:
            raise ValueError(f"unknown severity: {self.severity}")

    @property
    def severity_rank(self) -> int:
        return _SEVERITY_RANK[self.severity]


@dataclass(frozen=True)
class TwinModel:
    assets: tuple[TwinAsset, ...]
    relations: tuple[TwinRelation, ...]
    weaknesses: tuple[TwinWeakness, ...]

    def asset(self, asset_id: str) -> TwinAsset | None:
        for a in self.assets:
            if a.id == asset_id:
                return a
        return None

    def out_relations(self, asset_id: str) -> tuple[TwinRelation, ...]:
        return tuple(r for r in self.relations if r.src == asset_id)

    def weaknesses_of(self, asset_id: str) -> tuple[TwinWeakness, ...]:
        return tuple(w for w in self.weaknesses if w.asset_id == asset_id)


def build_twin(
    assets: list[TwinAsset],
    relations: list[TwinRelation],
    weaknesses: list[TwinWeakness] | None = None,
) -> TwinModel:
    """Validate and freeze a twin. Sorted deterministically."""
    if not assets:
        raise ValueError("a twin needs at least one asset")
    ids = [a.id for a in assets]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate asset id")
    known = set(ids)
    for r in relations:
        if r.src not in known or r.dst not in known:
            raise ValueError(f"relation endpoint not an asset: {r.src} -> {r.dst}")
    weaknesses = weaknesses or []
    for w in weaknesses:
        if w.asset_id not in known:
            raise ValueError(f"weakness references an unknown asset: {w.asset_id}")

    return TwinModel(
        assets=tuple(sorted(assets, key=lambda a: a.id)),
        relations=tuple(sorted(relations, key=lambda r: (r.src, r.dst, r.kind.value))),
        weaknesses=tuple(
            sorted(weaknesses, key=lambda w: (w.asset_id, w.kind.value, -w.severity_rank))
        ),
    )
