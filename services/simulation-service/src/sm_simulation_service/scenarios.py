"""Run a `RunScenarioRequest` against `sm_ml.scenario` and, optionally, feed
the pipeline.

The synthetic environment is generated from the request's own `seed` — the
caller never supplies raw entities, so there is no way to smuggle a real id in
except by naming one, and `validate_spec` catches that before anything runs.
"""

from __future__ import annotations

from uuid import UUID

from sm_common.bus import EventBusProducer
from sm_contracts import RunScenarioRequest, ScenarioRunResult, SimEventOut
from sm_ml.scenario import ScenarioIsolationError, ScenarioSpec, build_synthetic_env, run_scenario

from .pipeline import feed_events

__all__ = ["IsolationRefusedError", "run_and_maybe_feed"]


class IsolationRefusedError(Exception):
    """Re-raised from `sm_ml.scenario.ScenarioIsolationError` with the same
    message, so the HTTP layer doesn't need to import the ml-py package."""


async def run_and_maybe_feed(
    req: RunScenarioRequest, tenant_id: UUID, producer: EventBusProducer | None
) -> ScenarioRunResult:
    env = build_synthetic_env(req.seed)
    spec = ScenarioSpec(
        name=req.name, kind=req.kind, seed=req.seed, target_host=req.target_host,
        target_identity=req.target_identity, intensity=req.intensity,
    )
    try:
        run = run_scenario(spec, env)
    except ScenarioIsolationError as exc:
        raise IsolationRefusedError(str(exc)) from exc

    fed = 0
    if req.feed_pipeline and producer is not None:
        fed = await feed_events(producer, tenant_id, run.scenario_id, run.events, env)

    return ScenarioRunResult(
        scenario_id=run.scenario_id, kind=req.kind, seed=req.seed,
        target_host=req.target_host, target_identity=req.target_identity, intensity=req.intensity,
        event_count=run.step_count,
        events=[
            SimEventOut(
                step=e.step, at_offset_s=e.at_offset_s, kind=e.kind.value, actor=e.actor,
                target=e.target, attributes=e.attributes, scenario_id=e.scenario_id,
            )
            for e in run.events
        ],
        fed_to_pipeline=req.feed_pipeline,
        fed_event_count=fed,
    )
