"""Cross-session stitching.

An attacker's activity is often split across sessions (a login here, a lateral
move an hour later, exfiltration the next day). `stitch_sessions` links sessions
that (a) share at least one entity and (b) are within `link_within_seconds` of
each other in time, into `StitchedTrack`s — the connected components of that
"shared-entity, temporally-adjacent" graph.

Deterministic: sessions are processed in id order and union-find merges are
order-independent. No RNG, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["Session", "StitchedTrack", "stitch_sessions"]


@dataclass(frozen=True)
class Session:
    session_id: str
    entity_ids: frozenset[str]
    start: float
    end: float

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id must be non-empty")
        if self.end < self.start:
            raise ValueError(f"session {self.session_id}: end < start")


@dataclass(frozen=True)
class StitchedTrack:
    track_id: int
    session_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    start: float
    end: float

    @property
    def span(self) -> float:
        return self.end - self.start


def _gap(a: Session, b: Session) -> float:
    """Seconds between two sessions; 0 if they overlap."""
    if a.end >= b.start and b.end >= a.start:
        return 0.0
    return b.start - a.end if b.start > a.end else a.start - b.end


def stitch_sessions(
    sessions: Iterable[Session], *, link_within_seconds: float
) -> tuple[StitchedTrack, ...]:
    ordered = sorted(sessions, key=lambda s: (s.start, s.session_id))
    n = len(ordered)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(n):
        for j in range(i + 1, n):
            a, b = ordered[i], ordered[j]
            if b.start - a.end > link_within_seconds and b.start > a.end:
                break  # sorted by start — nothing later can be closer
            if a.entity_ids & b.entity_ids and _gap(a, b) <= link_within_seconds:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    tracks: list[StitchedTrack] = []
    for track_id, (_, members) in enumerate(
        sorted(groups.items(), key=lambda kv: ordered[min(kv[1])].start)
    ):
        sess = [ordered[i] for i in members]
        entities: set[str] = set()
        for s in sess:
            entities |= s.entity_ids
        tracks.append(StitchedTrack(
            track_id=track_id,
            session_ids=tuple(sorted(s.session_id for s in sess)),
            entity_ids=tuple(sorted(entities)),
            start=min(s.start for s in sess),
            end=max(s.end for s in sess),
        ))
    return tuple(tracks)
