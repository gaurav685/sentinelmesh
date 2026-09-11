"""A deterministic `TwinModel` built from a `SyntheticEnvironment` (Phase 12).

Lets the simulation-service surface a twin, attack paths, and blast-radius
analysis without a second, independently-maintained asset inventory: the twin
is just a structural read of the same synthetic estate a scenario runs
against. Every id it emits is `sim-`-prefixed, so it is never confused with a
real digital twin fed from production discovery data.
"""

from __future__ import annotations

import re

from ..scenario.env import SyntheticEnvironment, SyntheticKind
from .model import AssetKind, RelationKind, TwinAsset, TwinModel, TwinRelation, TwinWeakness, WeaknessKind, build_twin

__all__ = ["twin_from_synthetic_env"]

#: Role -> criticality. A role not listed here (or on a workstation-tier
#: default) gets 0.3. Deterministic from the entity name `build_synthetic_env`
#: assigns, not from any randomness of its own.
_ROLE_CRITICALITY = {"dc": 0.95, "db": 0.9, "backup": 0.7, "app": 0.6, "file": 0.6}
_ROLE_WEAKNESS: dict[str, tuple[WeaknessKind, str]] = {
    "dc": (WeaknessKind.excessive_privilege, "domain controller holds standing admin trust"),
    "db": (WeaknessKind.unpatched_cve, "database host is behind on patching"),
    "web": (WeaknessKind.public_exposure, "internet-facing web tier"),
}
_ROLE_RE = re.compile(r"[a-z]+")


def _role_of(name: str) -> str:
    m = _ROLE_RE.match(name)
    return m.group(0) if m else name


def twin_from_synthetic_env(env: SyntheticEnvironment) -> TwinModel:
    """A twin over exactly the hosts, identities, and ips already in `env` —
    no asset here is anything other than a synthetic entity from that env."""
    hosts = env.by_kind(SyntheticKind.host)
    identities = env.by_kind(SyntheticKind.identity)
    ips = env.by_kind(SyntheticKind.ip)
    if not hosts or not ips:
        raise ValueError("a twin needs at least one host and one ip in the environment")

    assets: list[TwinAsset] = []
    for h in hosts:
        role = _role_of(h.name)
        assets.append(
            TwinAsset(
                id=h.id, kind=AssetKind.host, name=h.name,
                criticality=_ROLE_CRITICALITY.get(role, 0.3), tags=frozenset({role}),
            )
        )
    for ident in identities:
        assets.append(TwinAsset(id=ident.id, kind=AssetKind.identity, name=ident.name, criticality=0.4))
    for ip in ips:
        assets.append(TwinAsset(id=ip.id, kind=AssetKind.network, name=ip.name, criticality=0.2))

    by_role: dict[str, str] = {}
    for h in hosts:
        by_role.setdefault(_role_of(h.name), h.id)

    relations: list[TwinRelation] = []
    for i, h in enumerate(hosts):
        relations.append(
            TwinRelation(src=h.id, dst=ips[i % len(ips)].id, kind=RelationKind.connects_to, weight=0.9)
        )
    for i, ident in enumerate(identities):
        relations.append(
            TwinRelation(
                src=ident.id, dst=hosts[i % len(hosts)].id, kind=RelationKind.authenticates_to, weight=0.7
            )
        )
    # A fixed role-dependency graph: the shape an attacker who lands on the
    # public-facing tier would actually have to cross.
    role_edges = (
        ("web", "app", RelationKind.connects_to, 0.9),
        ("app", "db", RelationKind.depends_on, 0.8),
        ("app", "file", RelationKind.depends_on, 0.6),
        ("workstation", "dc", RelationKind.authenticates_to, 0.6),
        ("backup", "db", RelationKind.stores, 0.5),
    )
    for src_role, dst_role, rel_kind, weight in role_edges:
        src_id, dst_id = by_role.get(src_role), by_role.get(dst_role)
        if src_id is not None and dst_id is not None and src_id != dst_id:
            relations.append(TwinRelation(src=src_id, dst=dst_id, kind=rel_kind, weight=weight))
    if "dc" in by_role:
        dc_id = by_role["dc"]
        for host_role, host_id in by_role.items():
            if host_role != "dc" and host_id != dc_id:
                relations.append(TwinRelation(src=dc_id, dst=host_id, kind=RelationKind.trusts, weight=0.7))

    weaknesses: list[TwinWeakness] = []
    for weak_role, (weak_kind, detail) in _ROLE_WEAKNESS.items():
        weak_host_id = by_role.get(weak_role)
        if weak_host_id is not None:
            severity = "critical" if weak_role == "dc" else "high"
            weaknesses.append(
                TwinWeakness(asset_id=weak_host_id, kind=weak_kind, severity=severity, detail=detail)
            )

    return build_twin(assets, relations, weaknesses)
