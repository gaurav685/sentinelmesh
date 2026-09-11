from __future__ import annotations

import pytest
from pydantic import ValidationError

from sm_ml.scenario import (
    ScenarioIsolationError,
    ScenarioKind,
    ScenarioSpec,
    SimEventKind,
    build_synthetic_env,
    is_synthetic_id,
    replay_run,
    run_scenario,
    validate_spec,
)
from sm_ml.scenario.errors import ScenarioError


def _env(seed: int = 7):
    return build_synthetic_env(seed, hosts=4, identities=3, ips=3)


def _spec(env, kind: ScenarioKind, **over) -> ScenarioSpec:
    host = next(e.id for e in env.entities if e.kind.value == "host")
    identity = next(e.id for e in env.entities if e.kind.value == "identity")
    kw = {"name": f"t-{kind.value}", "kind": kind, "seed": 1, "target_host": host,
          "target_identity": identity}
    kw.update(over)
    return ScenarioSpec(**kw)


def test_synthetic_env_is_deterministic_and_every_id_is_marked() -> None:
    a, b = _env(), _env()
    assert a == b
    assert all(is_synthetic_id(e.id) for e in a.entities)
    assert all(e.synthetic for e in a.entities)


def test_synthetic_env_differs_by_seed() -> None:
    assert _env(1) != _env(2)


def test_scenario_spec_is_frozen_and_closed() -> None:
    env = _env()
    spec = _spec(env, ScenarioKind.brute_force)
    with pytest.raises(ValidationError):
        ScenarioSpec.model_validate({**spec.model_dump(), "extra_field": 1})


@pytest.mark.parametrize("bad_host", ["host-01", "real-host-01", "prod-db"])
def test_a_non_synthetic_target_is_refused(bad_host: str) -> None:
    env = _env()
    identity = next(e.id for e in env.entities if e.kind.value == "identity")
    spec = ScenarioSpec(
        name="hostile", kind=ScenarioKind.apt, target_host=bad_host, target_identity=identity
    )
    with pytest.raises(ScenarioIsolationError, match="not a synthetic id"):
        validate_spec(spec, env)


def test_a_synthetic_id_not_in_this_env_is_refused() -> None:
    env = _env()
    identity = next(e.id for e in env.entities if e.kind.value == "identity")
    spec = ScenarioSpec(
        name="ghost", kind=ScenarioKind.apt, target_host="sim-host-99", target_identity=identity
    )
    with pytest.raises(ScenarioIsolationError, match="not present"):
        validate_spec(spec, env)


def test_run_scenario_is_deterministic() -> None:
    env = _env()
    spec = _spec(env, ScenarioKind.apt)
    a = run_scenario(spec, env)
    b = run_scenario(spec, env)
    assert a == b
    assert a.scenario_id == b.scenario_id
    assert a.synthetic is True
    assert all(e.simulated and e.scenario_id == a.scenario_id for e in a.events)


def test_run_scenario_events_are_ordered_by_offset() -> None:
    env = _env()
    run = run_scenario(_spec(env, ScenarioKind.apt), env)
    offsets = [e.at_offset_s for e in run.events]
    assert offsets == sorted(offsets)


def test_intensity_scales_event_volume() -> None:
    env = _env()
    light = run_scenario(_spec(env, ScenarioKind.ransomware, intensity=1), env)
    heavy = run_scenario(_spec(env, ScenarioKind.ransomware, intensity=5), env)
    assert heavy.step_count > light.step_count


@pytest.mark.parametrize(
    ("kind", "expected_kinds"),
    [
        (ScenarioKind.brute_force, {SimEventKind.auth_failed, SimEventKind.auth_success}),
        (
            ScenarioKind.apt,
            {SimEventKind.network_flow, SimEventKind.auth_success, SimEventKind.file_access},
        ),
        (
            ScenarioKind.ransomware,
            {SimEventKind.auth_success, SimEventKind.process_exec, SimEventKind.file_access},
        ),
        (ScenarioKind.insider, {SimEventKind.auth_success, SimEventKind.file_access}),
    ],
)
def test_each_scenario_kind_produces_its_expected_event_kinds(kind, expected_kinds) -> None:
    env = _env()
    run = run_scenario(_spec(env, kind), env)
    seen = {e.kind for e in run.events}
    assert expected_kinds <= seen


def test_brute_force_ends_in_one_success_after_the_failure_burst() -> None:
    env = _env()
    run = run_scenario(_spec(env, ScenarioKind.brute_force, intensity=2), env)
    assert run.events[-1].kind is SimEventKind.auth_success
    failures = [e for e in run.events if e.kind is SimEventKind.auth_failed]
    assert len(failures) == 12  # 6 * intensity(2)


def test_replay_run_slices_deterministically() -> None:
    env = _env()
    run = run_scenario(_spec(env, ScenarioKind.apt), env)
    full = list(replay_run(run))
    sliced = list(replay_run(run, from_step=2, to_step=5))
    assert sliced == full[2:5]
    assert list(replay_run(run, from_step=0, to_step=3)) == list(
        replay_run(run, from_step=0, to_step=3)
    )


def test_replay_run_rejects_an_inverted_window() -> None:
    env = _env()
    run = run_scenario(_spec(env, ScenarioKind.brute_force), env)
    with pytest.raises(ScenarioError, match="invalid replay window"):
        list(replay_run(run, from_step=5, to_step=1))
