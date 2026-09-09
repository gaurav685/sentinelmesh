"""`EventTimeline` — an ordered, de-duplicated stream of `TemporalEvent`.

Handles the four things the phase calls out:

- **duplicate events** — dropped by `event_id` (`add` returns `False`).
- **out-of-order events** — inserted in effective-time order regardless of
  arrival order; the timeline is always sorted.
- **clock skew** — each event's position uses `effective_time` (occurred_at
  clamped to ingest + max_skew); a clamped event is counted in `skew_corrected`.
- **missing events** — tolerated; `gaps()` reports intervals longer than a
  threshold so a consumer can decide whether a gap matters.

Deterministic: `add` uses `bisect` on `(effective_time, event_id)`, so the same
set of events always yields the same order, independent of insertion order.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from .events import TemporalEvent

__all__ = ["EventTimeline", "TimelineGap"]

_DEFAULT_MAX_SKEW = 300.0


@dataclass(frozen=True)
class TimelineGap:
    after_event_id: str
    before_event_id: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class EventTimeline:
    max_skew_seconds: float = _DEFAULT_MAX_SKEW
    _keys: list[tuple[float, str]] = field(default_factory=list, repr=False)
    _events: list[TemporalEvent] = field(default_factory=list, repr=False)
    _seen: set[str] = field(default_factory=set, repr=False)
    skew_corrected: int = 0
    duplicates_dropped: int = 0

    def add(self, event: TemporalEvent) -> bool:
        if event.event_id in self._seen:
            self.duplicates_dropped += 1
            return False
        t, clamped = event.effective_time(self.max_skew_seconds)
        if clamped:
            self.skew_corrected += 1
        key = (t, event.event_id)
        pos = bisect.bisect_left(self._keys, key)
        self._keys.insert(pos, key)
        self._events.insert(pos, event)
        self._seen.add(event.event_id)
        return True

    def extend(self, events: Iterable[TemporalEvent]) -> int:
        return sum(1 for e in events if self.add(e))

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[TemporalEvent]:
        return iter(self._events)

    def events(self) -> tuple[TemporalEvent, ...]:
        return tuple(self._events)

    def effective_time(self, event: TemporalEvent) -> float:
        return event.effective_time(self.max_skew_seconds)[0]

    def between(self, start: float, end: float) -> tuple[TemporalEvent, ...]:
        lo = bisect.bisect_left(self._keys, (start, ""))
        hi = bisect.bisect_right(self._keys, (end, chr(0x10FFFF)))
        return tuple(self._events[lo:hi])

    def span(self) -> tuple[float, float] | None:
        if not self._keys:
            return None
        return self._keys[0][0], self._keys[-1][0]

    def gaps(self, threshold_seconds: float) -> tuple[TimelineGap, ...]:
        out: list[TimelineGap] = []
        for (t0, _), (t1, _), e0, e1 in zip(
            self._keys, self._keys[1:], self._events, self._events[1:], strict=False
        ):
            if t1 - t0 > threshold_seconds:
                out.append(TimelineGap(e0.event_id, e1.event_id, t0, t1))
        return tuple(out)
