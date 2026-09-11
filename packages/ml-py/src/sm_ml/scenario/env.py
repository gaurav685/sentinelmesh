"""The synthetic environment a scenario runs in.

Entities here are **generated**, deterministic from a seed, and never real. Every
id is prefixed `sim-` so it can never be confused with a production entity, and
`is_synthetic_id` is the check every scenario target passes through.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "SyntheticEntity",
    "SyntheticEnvironment",
    "SyntheticKind",
    "build_synthetic_env",
    "is_synthetic_id",
]

_SIM_PREFIX = "sim-"


def is_synthetic_id(entity_id: str) -> bool:
    return entity_id.startswith(_SIM_PREFIX)


class SyntheticKind(StrEnum):
    identity = "identity"
    host = "host"
    ip = "ip"
    process = "process"
    file = "file"


@dataclass(frozen=True)
class SyntheticEntity:
    id: str
    kind: SyntheticKind
    name: str
    #: Always True. A synthetic entity is never a real asset.
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not is_synthetic_id(self.id):
            raise ValueError(f"a synthetic entity id must start with {_SIM_PREFIX!r}: {self.id}")


@dataclass(frozen=True)
class SyntheticEnvironment:
    seed: int
    entities: tuple[SyntheticEntity, ...]
    synthetic: bool = field(default=True)

    def by_kind(self, kind: SyntheticKind) -> tuple[SyntheticEntity, ...]:
        return tuple(e for e in self.entities if e.kind is kind)

    def get(self, entity_id: str) -> SyntheticEntity | None:
        for e in self.entities:
            if e.id == entity_id:
                return e
        return None

    def ids(self) -> frozenset[str]:
        return frozenset(e.id for e in self.entities)


def build_synthetic_env(
    seed: int, *, hosts: int = 6, identities: int = 5, ips: int = 6
) -> SyntheticEnvironment:
    """A small, deterministic synthetic estate. Same seed -> identical env."""
    rng = random.Random(seed)  # noqa: S311 - a deterministic fixture generator, not crypto
    entities: list[SyntheticEntity] = []
    roles = ["web", "app", "db", "file", "dc", "workstation", "backup", "jump"]
    for i in range(max(1, hosts)):
        role = roles[i % len(roles)]
        entities.append(
            SyntheticEntity(id=f"{_SIM_PREFIX}host-{i:02d}", kind=SyntheticKind.host, name=f"{role}{i:02d}")
        )
    people = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi"]
    for i in range(max(1, identities)):
        n = people[i % len(people)]
        entities.append(
            SyntheticEntity(id=f"{_SIM_PREFIX}id-{n}", kind=SyntheticKind.identity, name=n)
        )
    for i in range(max(1, ips)):
        octet = 10 + rng.randint(0, 240)
        entities.append(
            SyntheticEntity(
                id=f"{_SIM_PREFIX}ip-{i:02d}", kind=SyntheticKind.ip, name=f"10.99.{i}.{octet}"
            )
        )
    return SyntheticEnvironment(seed=seed, entities=tuple(sorted(entities, key=lambda e: e.id)))
