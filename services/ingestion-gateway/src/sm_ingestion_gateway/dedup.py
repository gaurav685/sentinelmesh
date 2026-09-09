"""At-most-once delivery of a single event, keyed on `(sensor_id, client_event_id)`.

A sensor that retries a `POST /api/v1/ingest/{source_type}` after a network
timeout can set the same `X-Sensor-Event-Id` on the retry. `Dedup.check_and_mark`
records the id in Redis with a short TTL and reports whether it was already
there; the route then returns `200` without re-sinking the event.

This is a convenience on top of the bus's at-least-once guarantee — downstream
consumers must still be idempotent on `event_id`. So a Redis outage does **not**
reject the request: `check_and_mark` returns `DedupState.unavailable` and the
route proceeds to sink the event (metered as `sm_ingest_dedup_errors_total`).
"""

from __future__ import annotations

from enum import Enum, auto
from uuid import UUID

import redis.asyncio as aioredis
import structlog

__all__ = ["Dedup", "DedupState"]

_log = structlog.get_logger("sm.ingestion.dedup")


class DedupState(Enum):
    fresh = auto()  # not seen before; proceed and sink
    duplicate = auto()  # seen within the TTL; do not re-sink
    unavailable = auto()  # store error; proceed and sink, but metered


class Dedup:
    def __init__(
        self, client: aioredis.Redis, *, ttl_seconds: int, key_prefix: str = "sm"
    ) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    def _key(self, sensor_id: UUID, client_event_id: str) -> str:
        return f"{self._prefix}:ingest:dedup:{sensor_id}:{client_event_id}"

    async def check_and_mark(self, sensor_id: UUID, client_event_id: str) -> DedupState:
        key = self._key(sensor_id, client_event_id)
        try:
            # SET key 1 NX EX ttl — atomic: only the first caller gets a truthy
            # reply, every retry within the TTL gets None.
            was_set = await self._client.set(key, "1", nx=True, ex=self._ttl)
        except Exception:
            _log.warning("dedup_store_unavailable", sensor_id=str(sensor_id))
            return DedupState.unavailable
        return DedupState.fresh if was_set else DedupState.duplicate

    async def forget(self, sensor_id: UUID, client_event_id: str) -> None:
        """Drop the mark for an id whose request was rejected (4xx). The event
        was never accepted, so a corrected retry with the same id must be able
        to get through rather than be suppressed as a duplicate."""
        try:
            await self._client.delete(self._key(sensor_id, client_event_id))
        except Exception:
            _log.warning("dedup_forget_failed", sensor_id=str(sensor_id))
