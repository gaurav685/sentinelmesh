"""Deterministic telemetry -> canonical mapping.

One mapper per `telemetry.*` payload turns the sensor's view into a
`CanonicalEventPayload`: a normalized verb, an `actor` and `target` entity, the
full entity list, and flat `attributes`. No enrichment happens here — Geo-IP,
hostname resolution, identity stitching and threat-intel tagging are separate
`enrich` providers that run after the mapping.

`normalize(envelope)` dispatches on `event_type` and raises `UnknownEventTypeError`
for anything not in `MAPPERS` (the engine dead-letters that).
"""

from __future__ import annotations

from .mappers import MAPPERS, UnknownEventTypeError, normalize

__all__ = ["MAPPERS", "UnknownEventTypeError", "normalize"]
