from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sm_contracts import CanonicalEventPayload, CanonicalKind, EntityRef, EventType

_RAW_TYPE = {
    CanonicalKind.auth: EventType.telemetry_auth_event,
    CanonicalKind.network_flow: EventType.telemetry_network_flow,
    CanonicalKind.dns: EventType.telemetry_dns_query,
    CanonicalKind.process_exec: EventType.telemetry_process_exec,
    CanonicalKind.file_access: EventType.telemetry_file_access,
}


def canonical(
    kind: CanonicalKind,
    *,
    action: str = "did",
    outcome: str | None = None,
    actor: tuple[str, str] | None = None,
    target: tuple[str, str] | None = None,
    attributes: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> CanonicalEventPayload:
    refs: list[EntityRef] = []
    a = EntityRef(kind=actor[0], value=actor[1]) if actor else None
    t = EntityRef(kind=target[0], value=target[1]) if target else None
    refs = [r for r in (a, t) if r is not None]
    return CanonicalEventPayload(
        kind=kind,
        occurred_at=occurred_at or datetime(2026, 3, 4, 14, 30, tzinfo=UTC),
        action=action,
        outcome=outcome,
        actor=a,
        target=t,
        entities=refs,
        raw_event_id=__import__("uuid").uuid4(),
        raw_event_type=_RAW_TYPE[kind],
        attributes=attributes or {},
    )
