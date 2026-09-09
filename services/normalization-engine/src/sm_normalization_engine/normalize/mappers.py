"""The per-source-type mappers.

Each mapper takes a typed telemetry payload and returns the canonical-specific
core (`_Core`); `normalize` attaches the lineage (`raw_event_id`,
`raw_event_type`) and the event time from the envelope.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sm_contracts import (
    CanonicalEventPayload,
    CanonicalKind,
    EntityKind,
    EntityRef,
    EventEnvelope,
    EventType,
)
from sm_contracts.telemetry import (
    AuthEventPayload,
    AuthOutcome,
    DnsQueryPayload,
    FileAccessPayload,
    NetworkFlowPayload,
    ProcessExecPayload,
)

__all__ = ["MAPPERS", "UnknownEventTypeError", "normalize"]

_ENTITY_VALUE_MAX = 512


class UnknownEventTypeError(ValueError):
    """`event_type` has no mapper — the engine dead-letters the record."""


@dataclass(frozen=True)
class _Core:
    kind: CanonicalKind
    action: str
    outcome: str | None
    actor: EntityRef | None
    target: EntityRef | None
    entities: list[EntityRef]
    attributes: dict[str, Any]


def _ref(kind: EntityKind, value: str | None) -> EntityRef | None:
    return EntityRef(kind=kind, value=value[:_ENTITY_VALUE_MAX]) if value else None


def _ip_or_domain_ref(value: str) -> EntityRef:
    try:
        ipaddress.ip_address(value)
        return EntityRef(kind=EntityKind.ip, value=value)
    except ValueError:
        return EntityRef(kind=EntityKind.domain, value=value[:_ENTITY_VALUE_MAX])


def _dedupe(refs: Iterable[EntityRef | None]) -> list[EntityRef]:
    seen: set[tuple[str, str]] = set()
    out: list[EntityRef] = []
    for ref in refs:
        if ref is None:
            continue
        key = (ref.kind.value, ref.value)
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    """Drop nulls; render non-JSON-native values as strings."""
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if value is None:
            continue
        out[key] = value if isinstance(value, (str, int, float, bool, list, dict)) else str(value)
    return out


def _network_flow(p: NetworkFlowPayload) -> _Core:
    actor = EntityRef(kind=EntityKind.ip, value=str(p.src_ip))
    target = EntityRef(kind=EntityKind.ip, value=str(p.dst_ip))
    return _Core(
        kind=CanonicalKind.network_flow,
        action="connected_to",
        outcome=p.verdict,
        actor=actor,
        target=target,
        entities=_dedupe(
            [actor, target, _ref(EntityKind.host, p.src_host), _ref(EntityKind.host, p.dst_host)]
        ),
        attributes=_clean(
            {
                "protocol": p.protocol, "app_protocol": p.app_protocol,
                "src_port": p.src_port, "dst_port": p.dst_port,
                "bytes_sent": p.bytes_sent, "bytes_received": p.bytes_received,
                "packets_sent": p.packets_sent, "packets_received": p.packets_received,
                "direction": p.direction.value, "ended_at": p.ended_at,
            }
        ),
    )


def _auth(p: AuthEventPayload) -> _Core:
    actor = EntityRef(kind=EntityKind.identity, value=p.principal[:_ENTITY_VALUE_MAX])
    target = _ref(EntityKind.host, p.target_host or p.source_host)
    action = (
        "authentication_succeeded" if p.outcome is AuthOutcome.success else "authentication_failed"
    )
    return _Core(
        kind=CanonicalKind.auth,
        action=action,
        outcome=p.outcome.value,
        actor=actor,
        target=target,
        entities=_dedupe(
            [actor, target, _ref(EntityKind.host, p.source_host),
             _ref(EntityKind.ip, str(p.source_ip) if p.source_ip else None)]
        ),
        attributes=_clean(
            {"auth_type": p.auth_type, "logon_id": p.logon_id,
             "failure_reason": p.failure_reason, "source_host": p.source_host,
             "source_ip": str(p.source_ip) if p.source_ip else None}
        ),
    )


def _dns(p: DnsQueryPayload) -> _Core:
    actor = EntityRef(kind=EntityKind.ip, value=str(p.client_ip))
    target = EntityRef(kind=EntityKind.domain, value=p.query_name[:_ENTITY_VALUE_MAX])
    return _Core(
        kind=CanonicalKind.dns,
        action="resolved",
        outcome=p.response_code,
        actor=actor,
        target=target,
        entities=_dedupe(
            [actor, target, *(_ip_or_domain_ref(a) for a in p.answers),
             _ref(EntityKind.host, p.client_host),
             _ref(EntityKind.ip, str(p.resolver_ip) if p.resolver_ip else None)]
        ),
        attributes=_clean(
            {"query_type": p.query_type, "response_code": p.response_code,
             "answers": p.answers, "client_host": p.client_host,
             "resolver_ip": str(p.resolver_ip) if p.resolver_ip else None}
        ),
    )


def _process_exec(p: ProcessExecPayload) -> _Core:
    host_ref = EntityRef(kind=EntityKind.host, value=p.host[:_ENTITY_VALUE_MAX])
    actor = _ref(EntityKind.identity, p.user) or host_ref
    target = EntityRef(kind=EntityKind.process, value=p.process_name[:_ENTITY_VALUE_MAX])
    return _Core(
        kind=CanonicalKind.process_exec,
        action="executed",
        outcome=None,
        actor=actor,
        target=target,
        entities=_dedupe([actor, target, host_ref, _ref(EntityKind.process, p.parent_process_name)]),
        attributes=_clean(
            {"process_path": p.process_path, "command_line": p.command_line,
             "process_id": p.process_id, "parent_process_name": p.parent_process_name,
             "parent_process_id": p.parent_process_id, "hash_sha256": p.hash_sha256,
             "signed": p.signed}
        ),
    )


def _file_access(p: FileAccessPayload) -> _Core:
    host_ref = EntityRef(kind=EntityKind.host, value=p.host[:_ENTITY_VALUE_MAX])
    actor = (
        _ref(EntityKind.identity, p.user)
        or _ref(EntityKind.process, p.process_name)
        or host_ref
    )
    target = EntityRef(kind=EntityKind.file, value=p.path[:_ENTITY_VALUE_MAX])
    return _Core(
        kind=CanonicalKind.file_access,
        action=p.action.value,
        outcome=None,
        actor=actor,
        target=target,
        entities=_dedupe([actor, target, host_ref, _ref(EntityKind.process, p.process_name)]),
        attributes=_clean(
            {"process_name": p.process_name, "process_id": p.process_id,
             "hash_sha256": p.hash_sha256, "full_path": p.path}
        ),
    )


_BY_TYPE: dict[EventType, Callable[[Any], _Core]] = {
    EventType.telemetry_network_flow: _network_flow,
    EventType.telemetry_auth_event: _auth,
    EventType.telemetry_dns_query: _dns,
    EventType.telemetry_process_exec: _process_exec,
    EventType.telemetry_file_access: _file_access,
}

MAPPERS = frozenset(_BY_TYPE)


def normalize(envelope: EventEnvelope[Any]) -> CanonicalEventPayload:
    mapper = _BY_TYPE.get(envelope.event_type)
    if mapper is None:
        raise UnknownEventTypeError(f"no mapper for event_type '{envelope.event_type.value}'")
    core = mapper(envelope.payload)
    return CanonicalEventPayload(
        kind=core.kind,
        occurred_at=envelope.occurred_at,
        action=core.action,
        outcome=core.outcome,
        actor=core.actor,
        target=core.target,
        entities=core.entities,
        raw_event_id=envelope.event_id,
        raw_event_type=envelope.event_type,
        attributes=core.attributes,
        enrichment={},
    )
