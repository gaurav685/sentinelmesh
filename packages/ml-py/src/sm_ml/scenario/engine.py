"""`run_scenario` — turn a validated `ScenarioSpec` into a deterministic,
ordered list of synthetic telemetry events.

Same spec + same env => byte-identical `ScenarioRun` (a seeded RNG, sorted
output). Nothing here touches a network or a real system.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .env import SyntheticEnvironment, SyntheticKind
from .events import SimEvent, SimEventKind
from .spec import ScenarioKind, ScenarioSpec, validate_spec

__all__ = ["ScenarioRun", "run_scenario"]

_NAMESPACE = uuid.UUID("5f3d9a2e-11c4-4d8b-9e77-000000000012")
_MAX_EVENTS = 2000


def scenario_id_for(spec: ScenarioSpec) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{spec.name}|{spec.kind.value}|{spec.seed}|{spec.intensity}"))


@dataclass(frozen=True)
class ScenarioRun:
    scenario_id: str
    spec: ScenarioSpec
    events: tuple[SimEvent, ...]
    #: Always True — a scenario run is a synthetic drill, never real activity.
    synthetic: bool = True

    @property
    def step_count(self) -> int:
        return len(self.events)


def run_scenario(spec: ScenarioSpec, env: SyntheticEnvironment) -> ScenarioRun:
    validate_spec(spec, env)
    sid = scenario_id_for(spec)
    rng = random.Random(f"{sid}:{spec.seed}")  # noqa: S311 - deterministic scenario generator
    builder = _TEMPLATES[spec.kind]
    raw = builder(spec, env, rng)

    events = tuple(
        SimEvent(
            step=i,
            at_offset_s=ev.at_offset_s,
            kind=ev.kind,
            actor=ev.actor,
            target=ev.target,
            attributes=dict(ev.attributes),
            scenario_id=sid,
        )
        for i, ev in enumerate(sorted(raw, key=lambda e: (e.at_offset_s, e.kind.value, e.actor)))
        if i < _MAX_EVENTS
    )
    return ScenarioRun(scenario_id=sid, spec=spec, events=events)


# --------------------------------------------------------------------------- #
# templates — each is a pure function of (spec, env, seeded rng)
# --------------------------------------------------------------------------- #
Builder = Callable[[ScenarioSpec, SyntheticEnvironment, random.Random], list[SimEvent]]


def _other_host(env: SyntheticEnvironment, not_id: str, rng: random.Random) -> str:
    hosts = [h.id for h in env.by_kind(SyntheticKind.host) if h.id != not_id]
    return hosts[rng.randrange(len(hosts))] if hosts else not_id


def _an_ip(env: SyntheticEnvironment, rng: random.Random) -> str:
    ips = [i.id for i in env.by_kind(SyntheticKind.ip)]
    return ips[rng.randrange(len(ips))] if ips else "sim-ip-00"


def _brute_force(spec: ScenarioSpec, env: SyntheticEnvironment, rng: random.Random) -> list[SimEvent]:
    src = _an_ip(env, rng)
    n = 6 * spec.intensity
    out = [
        SimEvent(
            step=0, at_offset_s=k * 3, kind=SimEventKind.auth_failed,
            actor=src, target=spec.target_identity, attributes={"reason": "bad_password"},
        )
        for k in range(n)
    ]
    out.append(
        SimEvent(
            step=0, at_offset_s=n * 3 + 2, kind=SimEventKind.auth_success,
            actor=src, target=spec.target_identity, attributes={"note": "after_burst"},
        )
    )
    return out


def _apt(spec: ScenarioSpec, env: SyntheticEnvironment, rng: random.Random) -> list[SimEvent]:
    src = _an_ip(env, rng)
    pivot = _other_host(env, spec.target_host, rng)
    out: list[SimEvent] = []
    # recon
    for k in range(3 * spec.intensity):
        out.append(SimEvent(
            step=0, at_offset_s=k * 5, kind=SimEventKind.network_flow,
            actor=src, target=spec.target_host, attributes={"phase": "recon", "port": str(20 + k)},
        ))
    base = 3 * spec.intensity * 5
    # initial access
    out.append(SimEvent(
        step=0, at_offset_s=base + 10, kind=SimEventKind.auth_success,
        actor=src, target=spec.target_identity, attributes={"phase": "initial_access", "vector": "phish"},
    ))
    # lateral movement
    out.append(SimEvent(
        step=0, at_offset_s=base + 60, kind=SimEventKind.auth_success,
        actor=spec.target_host, target=pivot, attributes={"phase": "lateral_movement"},
    ))
    # collection
    for k in range(2 * spec.intensity):
        out.append(SimEvent(
            step=0, at_offset_s=base + 120 + k * 4, kind=SimEventKind.file_access,
            actor=spec.target_identity, target=f"sim-file-{k:02d}",
            attributes={"phase": "collection", "op": "read"},
        ))
    # exfil
    out.append(SimEvent(
        step=0, at_offset_s=base + 300, kind=SimEventKind.network_flow,
        actor=pivot, target=src, attributes={"phase": "exfiltration", "bytes": str(10_000 * spec.intensity)},
    ))
    return out


def _ransomware(spec: ScenarioSpec, env: SyntheticEnvironment, rng: random.Random) -> list[SimEvent]:
    src = _an_ip(env, rng)
    out = [
        SimEvent(
            step=0, at_offset_s=0, kind=SimEventKind.auth_success,
            actor=src, target=spec.target_identity, attributes={"phase": "initial_access"},
        ),
    ]
    # discovery
    for k in range(2 * spec.intensity):
        out.append(SimEvent(
            step=0, at_offset_s=10 + k * 3, kind=SimEventKind.process_exec,
            actor=spec.target_host, target="sim-proc-enum",
            attributes={"phase": "discovery", "cmd": f"enum{k}"},
        ))
    # encryption bursts
    for k in range(10 * spec.intensity):
        out.append(SimEvent(
            step=0, at_offset_s=60 + k * 2, kind=SimEventKind.file_access,
            actor=spec.target_host, target=f"sim-file-{k % 20:02d}",
            attributes={"phase": "impact", "op": "write", "ext": ".locked"},
        ))
    return out


def _insider(spec: ScenarioSpec, env: SyntheticEnvironment, rng: random.Random) -> list[SimEvent]:
    unusual = _other_host(env, spec.target_host, rng)
    out = [
        SimEvent(
            step=0, at_offset_s=0, kind=SimEventKind.auth_success,
            actor=unusual, target=spec.target_identity,
            attributes={"phase": "access", "hour": "03", "note": "unusual_host"},
        ),
    ]
    for k in range(8 * spec.intensity):
        out.append(SimEvent(
            step=0, at_offset_s=30 + k * 2, kind=SimEventKind.file_access,
            actor=spec.target_identity, target=f"sim-file-hr-{k:02d}",
            attributes={"phase": "collection", "op": "read", "sensitivity": "high"},
        ))
    return out


_TEMPLATES: dict[ScenarioKind, Builder] = {
    ScenarioKind.brute_force: _brute_force,
    ScenarioKind.apt: _apt,
    ScenarioKind.ransomware: _ransomware,
    ScenarioKind.insider: _insider,
}
