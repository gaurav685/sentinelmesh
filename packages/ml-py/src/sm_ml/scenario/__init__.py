"""Synthetic attack-scenario engine (Phase 12).

    build_synthetic_env(seed) -> SyntheticEnvironment   (deterministic, all `sim-` ids)
    ScenarioSpec(kind=apt|ransomware|insider|brute_force, target_host=, target_identity=)
    validate_spec(spec, env)   — raises ScenarioIsolationError unless every target is synthetic
    run_scenario(spec, env)    -> ScenarioRun (deterministic, ordered synthetic telemetry)
    replay_run(run, from_step=, to_step=)   — read-only deterministic slice

Nothing here touches a network or a real system. Every emitted `SimEvent` is
`simulated=True` and carries its `scenario_id`.
"""

from __future__ import annotations

from .engine import ScenarioRun, run_scenario, scenario_id_for
from .env import (
    SyntheticEntity,
    SyntheticEnvironment,
    SyntheticKind,
    build_synthetic_env,
    is_synthetic_id,
)
from .errors import ScenarioError, ScenarioIsolationError
from .events import SimEvent, SimEventKind
from .replay import replay_run
from .spec import ScenarioKind, ScenarioSpec, validate_spec

__all__ = [
    "ScenarioError",
    "ScenarioIsolationError",
    "ScenarioKind",
    "ScenarioRun",
    "ScenarioSpec",
    "SimEvent",
    "SimEventKind",
    "SyntheticEntity",
    "SyntheticEnvironment",
    "SyntheticKind",
    "build_synthetic_env",
    "is_synthetic_id",
    "replay_run",
    "run_scenario",
    "scenario_id_for",
    "validate_spec",
]
