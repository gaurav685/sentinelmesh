"""The temporal event — the unit the timeline, graph state and replay work on.

A `TemporalEvent` is deliberately thin: an id (the idempotency key), two
timestamps (source time and ingest time), a kind, the entities it touches, and
flat attributes. Anything on the bus can be projected to one.

Clock skew: a source clock may run ahead of ingest. `effective_time` is
`occurred_at` clamped to `ingested_at + max_skew` — a source cannot be from the
future beyond a bounded tolerance. The clamp is recorded (`skew_corrected`) so a
downstream never silently trusts a bad clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["TemporalEvent"]


@dataclass(frozen=True)
class TemporalEvent:
    event_id: str
    occurred_at: float  # epoch seconds, from the source
    ingested_at: float  # epoch seconds, set on receipt
    kind: str
    entities: tuple[str, ...] = ()
    session_id: str | None = None
    attributes: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must be non-empty")
        if not self.kind:
            raise ValueError("kind must be non-empty")

    def effective_time(self, max_skew_seconds: float) -> tuple[float, bool]:
        """`(clamped_occurred_at, was_clamped)`."""
        ceiling = self.ingested_at + max_skew_seconds
        if self.occurred_at > ceiling:
            return ceiling, True
        return self.occurred_at, False
