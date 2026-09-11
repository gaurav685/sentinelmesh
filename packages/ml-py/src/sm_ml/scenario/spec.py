"""The scenario contract and its isolation check.

A `ScenarioSpec` names a synthetic attack to run inside a `SyntheticEnvironment`.
`validate_spec` is the safety gate: every target must be a synthetic entity that
exists in the env — a spec cannot reference a real or unknown id.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .env import SyntheticEnvironment, is_synthetic_id
from .errors import ScenarioIsolationError

__all__ = ["ScenarioKind", "ScenarioSpec", "validate_spec"]


class ScenarioKind(StrEnum):
    apt = "apt"
    ransomware = "ransomware"
    insider = "insider"
    brute_force = "brute_force"


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: ScenarioKind
    seed: int = Field(default=1, ge=0)
    #: The synthetic host the scenario centres on (a `sim-` id in the env).
    target_host: str = Field(min_length=1, max_length=96)
    #: The synthetic identity the scenario abuses (a `sim-` id in the env).
    target_identity: str = Field(min_length=1, max_length=96)
    #: 1 (a light touch) .. 5 (a loud, high-volume run). Scales event counts.
    intensity: int = Field(default=3, ge=1, le=5)


def validate_spec(spec: ScenarioSpec, env: SyntheticEnvironment) -> None:
    """Raise `ScenarioIsolationError` unless every target is a synthetic entity
    present in `env`."""
    env_ids = env.ids()
    for label, value in (("target_host", spec.target_host), ("target_identity", spec.target_identity)):
        if not is_synthetic_id(value):
            raise ScenarioIsolationError(
                f"{label} {value!r} is not a synthetic id — a scenario may only touch synthetic entities"
            )
        if value not in env_ids:
            raise ScenarioIsolationError(
                f"{label} {value!r} is not present in the synthetic environment"
            )
    if env.get(spec.target_host) is None or env.get(spec.target_identity) is None:
        raise ScenarioIsolationError("a scenario target is missing from the synthetic environment")
