"""Attack progression over time.

Given an ordered `EventTimeline` and a function that maps an event to an
`AttackStage` (e.g. via `sm_contracts.stage_for_technique` on the techniques a
detection named), produce the stage-over-time track: the furthest kill-chain
stage reached at each observed moment. It never regresses — a later low-stage
event does not undo a high-stage one — but the track records every transition so
an analyst can see the sequence and its timing.

`furthest_stage_at(t)` answers "how far had this progressed by time t". Pure
function of the timeline; no clock, no RNG.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sm_contracts import STAGE_ORDER, AttackStage

from .events import TemporalEvent
from .timeline import EventTimeline

__all__ = ["ProgressionPoint", "ProgressionTrack", "build_progression"]

StageFn = Callable[[TemporalEvent], AttackStage]


@dataclass(frozen=True)
class ProgressionPoint:
    at: float
    event_id: str
    stage: AttackStage
    furthest_stage: AttackStage
    is_advance: bool  # True when this event pushed the furthest stage forward


@dataclass(frozen=True)
class ProgressionTrack:
    points: tuple[ProgressionPoint, ...]

    @property
    def furthest_stage(self) -> AttackStage:
        return self.points[-1].furthest_stage if self.points else AttackStage.unknown

    def furthest_stage_at(self, t: float) -> AttackStage:
        reached = AttackStage.unknown
        for p in self.points:
            if p.at > t:
                break
            reached = p.furthest_stage
        return reached

    def advances(self) -> tuple[ProgressionPoint, ...]:
        return tuple(p for p in self.points if p.is_advance)


def build_progression(timeline: EventTimeline, stage_fn: StageFn) -> ProgressionTrack:
    points: list[ProgressionPoint] = []
    furthest = AttackStage.unknown
    for event in timeline:
        stage = stage_fn(event)
        is_advance = STAGE_ORDER[stage] > STAGE_ORDER[furthest]
        if is_advance:
            furthest = stage
        points.append(ProgressionPoint(
            at=timeline.effective_time(event), event_id=event.event_id,
            stage=stage, furthest_stage=furthest, is_advance=is_advance,
        ))
    return ProgressionTrack(points=tuple(points))
