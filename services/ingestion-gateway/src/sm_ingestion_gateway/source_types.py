"""The `{source_type}` path segment and what it maps to.

`POST /api/v1/ingest/{source_type}` accepts one of these five names. Each maps to
an `EventType` and, through `EVENT_PAYLOAD_REGISTRY`, to the payload model that
validates the request body. An unknown name is a 404 (the resource — that ingest
channel — does not exist), never a 422.
"""

from __future__ import annotations

from sm_common.errors import NotFound
from sm_contracts import EVENT_PAYLOAD_REGISTRY, EventType, SmBaseModel

__all__ = ["SOURCE_TYPES", "resolve_source_type"]

SOURCE_TYPES: dict[str, EventType] = {
    "network_flow": EventType.telemetry_network_flow,
    "auth_event": EventType.telemetry_auth_event,
    "dns_query": EventType.telemetry_dns_query,
    "process_exec": EventType.telemetry_process_exec,
    "file_access": EventType.telemetry_file_access,
}


def resolve_source_type(source_type: str) -> tuple[EventType, type[SmBaseModel]]:
    """Return `(event_type, payload_model)` for a `{source_type}` segment.

    Raises `NotFound` for anything not in `SOURCE_TYPES`.
    """
    event_type = SOURCE_TYPES.get(source_type)
    if event_type is None:
        raise NotFound(f"unknown ingest source type '{source_type}'")
    return event_type, EVENT_PAYLOAD_REGISTRY[event_type]
