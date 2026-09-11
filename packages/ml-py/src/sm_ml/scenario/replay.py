"""Deterministic, read-only replay of a scenario run.

`replay_run(run, from_step=, to_step=)` re-emits a contiguous slice of the
already-computed events. It computes nothing and touches nothing — a replay of a
replay is identical.
"""

from __future__ import annotations

from collections.abc import Iterator

from .engine import ScenarioRun
from .errors import ScenarioError
from .events import SimEvent

__all__ = ["replay_run"]


def replay_run(
    run: ScenarioRun, *, from_step: int = 0, to_step: int | None = None
) -> Iterator[SimEvent]:
    hi = run.step_count if to_step is None else to_step
    if from_step < 0 or hi < from_step:
        raise ScenarioError(f"invalid replay window: [{from_step}, {hi})")
    for ev in run.events:
        if from_step <= ev.step < hi:
            yield ev
