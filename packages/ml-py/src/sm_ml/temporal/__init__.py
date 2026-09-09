"""SentinelMesh temporal-intelligence engine (Phase 8).

    events -> EventTimeline (ordered, de-duplicated, skew-clamped)
           -> TemporalGraphState.at(t)     — the graph as it stood at t
           -> ProgressionTrack             — furthest kill-chain stage over time
           -> replay(from, to)             — deterministic historical replay
           -> stitch_sessions(...)         — cross-session correlation

Everything is standard-library and a pure function of its inputs: the same set of
events always yields the same timeline, the same state, the same replay order.
The four hard cases the phase calls out are handled explicitly — out-of-order
(sorted insert), duplicate (`event_id` de-dup), clock skew (bounded clamp),
missing (tolerated, `gaps()` reports them).
"""

from __future__ import annotations

from .events import TemporalEvent
from .graph_state import EdgeFn, TemporalGraphState, TemporalSnapshot
from .progression import ProgressionPoint, ProgressionTrack, build_progression
from .replay import ReplayCursor, replay
from .stitch import Session, StitchedTrack, stitch_sessions
from .timeline import EventTimeline, TimelineGap

__all__ = [
    "EdgeFn",
    "EventTimeline",
    "ProgressionPoint",
    "ProgressionTrack",
    "ReplayCursor",
    "Session",
    "StitchedTrack",
    "TemporalEvent",
    "TemporalGraphState",
    "TemporalSnapshot",
    "TimelineGap",
    "build_progression",
    "replay",
    "stitch_sessions",
]
