"""Simulation + deception contracts (Phase 12).

`services/simulation-service` runs synthetic attack scenarios against the
digital twin's synthetic environment and hosts the deception decoy registry.
**A decoy's `network_boundary` can never be `production`** — that value is not
in the allowed set, so a request for it fails schema validation before any
handler runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc

__all__ = [
    "Decoy",
    "DecoyInteraction",
    "DecoyInteractionIn",
    "DecoyKind",
    "NetworkBoundary",
    "RegisterDecoyRequest",
    "RunScenarioRequest",
    "ScenarioKind",
    "ScenarioRunResult",
    "SimEventOut",
]

ScenarioKind = Literal["apt", "ransomware", "insider", "brute_force"]

#: Deliberately excludes "production" — a decoy can never declare that
#: boundary. See ADR / §23: deception infra never connects to production
#: without an explicit control this build does not implement.
NetworkBoundary = Literal["isolated", "dmz-isolated"]
DecoyKind = Literal["honeypot_host", "honeytoken", "decoy_credential"]
DecoyStatus = Literal["active", "torn_down"]


class RunScenarioRequest(SmBaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ScenarioKind
    seed: int = Field(default=1, ge=0)
    #: A synthetic ("sim-"-prefixed) host/identity id. The synthetic environment
    #: is generated from the same `seed`, so these must be ids that environment
    #: would produce (the deterministic default naming is `sim-host-NN` /
    #: `sim-id-<name>`) — an unknown or non-synthetic id is refused.
    target_host: str = Field(min_length=1, max_length=96)
    target_identity: str = Field(min_length=1, max_length=96)
    intensity: int = Field(default=3, ge=1, le=5)
    #: When true, every emitted event is also produced onto `telemetry.raw`
    #: (source.type = "simulation") so it flows through the real detection
    #: pipeline, clearly labelled as a drill.
    feed_pipeline: bool = False


class SimEventOut(SmBaseModel):
    step: int = Field(ge=0)
    at_offset_s: int = Field(ge=0)
    kind: str = Field(min_length=1, max_length=32)
    actor: str = Field(min_length=1, max_length=96)
    target: str = Field(min_length=1, max_length=96)
    attributes: dict[str, str] = Field(default_factory=dict)
    simulated: bool = True
    scenario_id: str = Field(min_length=1, max_length=64)


class ScenarioRunResult(SmBaseModel):
    scenario_id: str = Field(min_length=1, max_length=64)
    kind: ScenarioKind
    seed: int
    target_host: str
    target_identity: str
    intensity: int
    event_count: int = Field(ge=0)
    events: list[SimEventOut] = Field(default_factory=list, max_length=2000)
    #: Always true — a scenario run is a synthetic drill, never real activity.
    synthetic: bool = True
    fed_to_pipeline: bool = False
    fed_event_count: int = Field(default=0, ge=0)


class RegisterDecoyRequest(SmBaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: DecoyKind
    network_boundary: NetworkBoundary
    ttl_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class Decoy(SmBaseModel):
    id: str
    tenant_id: str
    name: str
    kind: DecoyKind
    network_boundary: NetworkBoundary
    status: DecoyStatus
    ttl_seconds: int
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    torn_down_at: datetime | None = None

    @field_validator("created_at", "torn_down_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return to_utc(v) if v is not None else None


class DecoyInteractionIn(SmBaseModel):
    #: Where the interaction came from (an ip, a hostname) — attacker-supplied,
    #: never trusted for anything but display.
    source: str = Field(min_length=1, max_length=256)
    technique_hint: str | None = Field(default=None, max_length=64)
    detail: dict[str, str] = Field(default_factory=dict)


class DecoyInteraction(SmBaseModel):
    id: str
    decoy_id: str
    tenant_id: str
    source: str
    technique_hint: str | None = None
    detail: dict[str, str] = Field(default_factory=dict)
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)
