"""Rolling windows for adaptive thresholds and stateful rules.

In-process, bounded, per-tenant. A restart loses the warm-up (the windows refill
from the stream) — acceptable for Phase 5; Redis-backed shared windows are the
scale path and do not change the detection contract.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from uuid import UUID

from sm_contracts import CanonicalKind

__all__ = ["EventTimeline", "FeatureWindows"]


class FeatureWindows:
    """A capped deque of recent feature vectors per `(tenant_id, kind)`."""

    def __init__(self, *, size: int) -> None:
        self._size = size
        self._windows: dict[tuple[UUID, CanonicalKind], deque[list[float]]] = {}

    def _key(self, tenant_id: UUID, kind: CanonicalKind) -> tuple[UUID, CanonicalKind]:
        return (tenant_id, kind)

    def sample(self, tenant_id: UUID, kind: CanonicalKind) -> list[list[float]]:
        w = self._windows.get(self._key(tenant_id, kind))
        return list(w) if w else []

    def observe(self, tenant_id: UUID, kind: CanonicalKind, vector: list[float]) -> None:
        key = self._key(tenant_id, kind)
        w = self._windows.get(key)
        if w is None:
            w = deque(maxlen=self._size)
            self._windows[key] = w
        w.append(list(vector))

    def size(self, tenant_id: UUID, kind: CanonicalKind) -> int:
        w = self._windows.get(self._key(tenant_id, kind))
        return len(w) if w else 0


@dataclass
class _Bucket:
    events: deque[tuple[float, str]] = field(default_factory=deque)


class EventTimeline:
    """A time-bounded log of `(subject, tag)` events per tenant, for the stateful
    rule detectors (failed-login burst, credential reuse, lateral movement).
    Entries older than `window_s` are dropped lazily on access."""

    def __init__(self, *, window_s: int, max_per_tenant: int = 4096) -> None:
        self._window_s = window_s
        self._max = max_per_tenant
        self._by_tenant: dict[UUID, _Bucket] = {}

    def _bucket(self, tenant_id: UUID) -> _Bucket:
        b = self._by_tenant.get(tenant_id)
        if b is None:
            b = _Bucket()
            self._by_tenant[tenant_id] = b
        return b

    def _prune(self, b: _Bucket, now: float) -> None:
        cutoff = now - self._window_s
        while b.events and b.events[0][0] < cutoff:
            b.events.popleft()
        while len(b.events) > self._max:
            b.events.popleft()

    def record(self, tenant_id: UUID, subject: str, tag: str, *, at: float | None = None) -> None:
        now = at if at is not None else time.time()
        b = self._bucket(tenant_id)
        b.events.append((now, f"{tag}:{subject}"))
        self._prune(b, now)

    def recent(self, tenant_id: UUID, *, at: float | None = None) -> list[str]:
        now = at if at is not None else time.time()
        b = self._by_tenant.get(tenant_id)
        if b is None:
            return []
        self._prune(b, now)
        return [e[1] for e in b.events]

    def count(self, tenant_id: UUID, tag: str, subject: str, *, at: float | None = None) -> int:
        needle = f"{tag}:{subject}"
        return sum(1 for e in self.recent(tenant_id, at=at) if e == needle)

    def subjects(self, tenant_id: UUID, tag: str, *, at: float | None = None) -> set[str]:
        prefix = f"{tag}:"
        return {e[len(prefix):] for e in self.recent(tenant_id, at=at) if e.startswith(prefix)}
