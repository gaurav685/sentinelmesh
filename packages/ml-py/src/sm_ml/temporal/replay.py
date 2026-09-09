"""Deterministic historical replay.

`replay(timeline, from_t, to_t)` yields the events in `[from_t, to_t]` in
effective-time order — exactly what happened, in the order it effectively
happened, regardless of the order the events arrived. A `ReplayCursor` steps
through the same sequence and reports progress.

Replay is read-only and side-effect-free here: a service that replays to rebuild
state (`graph-writer` reprocessing, a re-scored detection) runs its own adapters
with side effects disabled (`replay_group`, event-model.md §6). This module only
guarantees the ordering and the boundaries.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from .events import TemporalEvent
from .timeline import EventTimeline

__all__ = ["ReplayCursor", "replay"]


def replay(
    timeline: EventTimeline, from_t: float | None = None, to_t: float | None = None
) -> Iterator[TemporalEvent]:
    span = timeline.span()
    if span is None:
        return
    lo = span[0] if from_t is None else from_t
    hi = span[1] if to_t is None else to_t
    if hi < lo:
        raise ValueError("replay window end is before its start")
    yield from timeline.between(lo, hi)


@dataclass
class ReplayCursor:
    timeline: EventTimeline
    from_t: float | None = None
    to_t: float | None = None
    _events: tuple[TemporalEvent, ...] = field(default_factory=tuple, repr=False)
    _pos: int = 0

    def __post_init__(self) -> None:
        self._events = tuple(replay(self.timeline, self.from_t, self.to_t))

    def __len__(self) -> int:
        return len(self._events)

    @property
    def remaining(self) -> int:
        return len(self._events) - self._pos

    @property
    def done(self) -> bool:
        return self._pos >= len(self._events)

    def next(self, n: int = 1) -> tuple[TemporalEvent, ...]:
        if n < 1:
            raise ValueError("n must be >= 1")
        batch = self._events[self._pos:self._pos + n]
        self._pos += len(batch)
        return batch

    def reset(self) -> None:
        self._pos = 0
