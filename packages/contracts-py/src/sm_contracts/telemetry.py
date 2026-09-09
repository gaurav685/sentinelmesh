"""Telemetry payload contracts (Phase 2; docs/CONTRACTS.md §2, ADR-018, R1/R2).

These are the payloads a **sensor** emits. They carry values as observed at the
source — IP addresses, ports, hostnames-as-seen, principal strings — with no
enrichment. Geo-IP, hostname resolution, identity stitching and threat-intel
tagging happen in `normalization-engine`, which produces `CanonicalEventPayload`.

Design rules:
- IP addresses are validated (`IPvAnyAddress`); a malformed address is a
  validation error, so the ingestion gateway can send it to the DLQ rather than
  store garbage.
- Every payload carries its own event time. The ingestion gateway copies it to
  the envelope's `occurred_at`; that stays the authoritative event time.
- Byte / packet counters are non-negative. Ports are 0-65535.
- Free-text fields (`command_line`, `path`, …) are length-bounded so a hostile
  or broken sensor cannot push an unbounded payload past the size cap by
  splitting it across fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, IPvAnyAddress, field_validator, model_validator

from .common import SmBaseModel, to_utc
from .events import EVENT_PAYLOAD_REGISTRY, EventType

__all__ = [
    "TELEMETRY_PAYLOADS",
    "AuthEventPayload",
    "AuthOutcome",
    "CanonicalEventPayload",
    "CanonicalKind",
    "Direction",
    "DnsQueryPayload",
    "EntityKind",
    "EntityRef",
    "FileAccessPayload",
    "FileAction",
    "NetworkFlowPayload",
    "ProcessExecPayload",
]

_HEX64 = r"^[0-9a-f]{64}$"


class Direction(StrEnum):
    inbound = "inbound"
    outbound = "outbound"
    lateral = "lateral"
    unknown = "unknown"


class AuthOutcome(StrEnum):
    success = "success"
    failure = "failure"


class FileAction(StrEnum):
    read = "read"
    write = "write"
    create = "create"
    delete = "delete"
    rename = "rename"
    execute = "execute"
    permission_change = "permission_change"


class _TimedPayload(SmBaseModel):
    """Shared: an event time the gateway lifts into the envelope."""

    occurred_at: datetime = Field(description="Event time as observed by the sensor. UTC.")

    @field_validator("occurred_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class NetworkFlowPayload(_TimedPayload):
    src_ip: IPvAnyAddress
    dst_ip: IPvAnyAddress
    src_port: int | None = Field(default=None, ge=0, le=65535)
    dst_port: int | None = Field(default=None, ge=0, le=65535)
    protocol: str = Field(min_length=1, max_length=16, description="Transport, e.g. tcp/udp/icmp.")
    app_protocol: str | None = Field(default=None, max_length=32, description="e.g. http, dns, ssh.")
    bytes_sent: int = Field(default=0, ge=0)
    bytes_received: int = Field(default=0, ge=0)
    packets_sent: int = Field(default=0, ge=0)
    packets_received: int = Field(default=0, ge=0)
    ended_at: datetime | None = None
    direction: Direction = Direction.unknown
    src_host: str | None = Field(default=None, max_length=253)
    dst_host: str | None = Field(default=None, max_length=253)
    verdict: str | None = Field(default=None, max_length=32, description="Firewall/IDS verdict if any.")

    @field_validator("protocol", "app_protocol")
    @classmethod
    def _lower(cls, v: str | None) -> str | None:
        return v.lower() if v else v

    @field_validator("ended_at")
    @classmethod
    def _end_utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else to_utc(v)

    @model_validator(mode="after")
    def _end_after_start(self) -> NetworkFlowPayload:
        if self.ended_at is not None and self.ended_at < self.occurred_at:
            raise ValueError("ended_at is before the flow start (occurred_at)")
        return self


class AuthEventPayload(_TimedPayload):
    outcome: AuthOutcome
    auth_type: str = Field(min_length=1, max_length=32, description="interactive/network/kerberos/ntlm/ssh/…")
    principal: str = Field(min_length=1, max_length=320, description="user@domain or username as seen.")
    source_host: str | None = Field(default=None, max_length=253)
    target_host: str | None = Field(default=None, max_length=253)
    source_ip: IPvAnyAddress | None = None
    logon_id: str | None = Field(default=None, max_length=128)
    failure_reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _failure_reason_only_on_failure(self) -> AuthEventPayload:
        if self.failure_reason and self.outcome is not AuthOutcome.failure:
            raise ValueError("failure_reason is only valid when outcome == 'failure'")
        return self


class DnsQueryPayload(_TimedPayload):
    client_ip: IPvAnyAddress
    client_host: str | None = Field(default=None, max_length=253)
    query_name: str = Field(min_length=1, max_length=253)
    query_type: str = Field(min_length=1, max_length=16, description="A, AAAA, CNAME, TXT, PTR, MX, …")
    response_code: str | None = Field(default=None, max_length=16, description="NOERROR/NXDOMAIN/SERVFAIL/…")
    answers: list[str] = Field(default_factory=list, max_length=64)
    resolver_ip: IPvAnyAddress | None = None

    @field_validator("query_type", "response_code")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @field_validator("answers")
    @classmethod
    def _bounded_answers(cls, v: list[str]) -> list[str]:
        for a in v:
            if not a:
                raise ValueError("a DNS answer is empty")
            if len(a) > 253:
                raise ValueError("a DNS answer exceeds 253 characters")
        return v


class ProcessExecPayload(_TimedPayload):
    host: str = Field(min_length=1, max_length=253)
    process_name: str = Field(min_length=1, max_length=256)
    process_path: str | None = Field(default=None, max_length=1024)
    command_line: str | None = Field(default=None, max_length=8192)
    process_id: int | None = Field(default=None, ge=0)
    parent_process_name: str | None = Field(default=None, max_length=256)
    parent_process_id: int | None = Field(default=None, ge=0)
    user: str | None = Field(default=None, max_length=320)
    hash_sha256: str | None = Field(default=None, pattern=_HEX64)
    signed: bool | None = None

    @field_validator("hash_sha256", mode="before")
    @classmethod
    def _lower_hash(cls, v: object) -> object:
        # `mode="before"` so the pattern constraint checks the lowered value.
        return v.lower() if isinstance(v, str) else v


class FileAccessPayload(_TimedPayload):
    host: str = Field(min_length=1, max_length=253)
    path: str = Field(min_length=1, max_length=4096)
    action: FileAction
    process_name: str | None = Field(default=None, max_length=256)
    process_id: int | None = Field(default=None, ge=0)
    user: str | None = Field(default=None, max_length=320)
    hash_sha256: str | None = Field(default=None, pattern=_HEX64)

    @field_validator("hash_sha256", mode="before")
    @classmethod
    def _lower_hash(cls, v: object) -> object:
        # `mode="before"` so the pattern constraint checks the lowered value.
        return v.lower() if isinstance(v, str) else v


# --------------------------------------------------------------------------- #
# canonical event (produced by normalization-engine)
# --------------------------------------------------------------------------- #
class EntityKind(StrEnum):
    identity = "identity"
    host = "host"
    ip = "ip"
    domain = "domain"
    process = "process"
    file = "file"


class CanonicalKind(StrEnum):
    network_flow = "network_flow"
    auth = "auth"
    dns = "dns"
    process_exec = "process_exec"
    file_access = "file_access"


class EntityRef(SmBaseModel):
    kind: EntityKind
    value: str = Field(min_length=1, max_length=512, description="Canonical identifier for the entity.")


class CanonicalEventPayload(SmBaseModel):
    """The normalized view of one telemetry event. Written by
    `normalization-engine`, consumed by the graph, detection and memory
    subsystems."""

    kind: CanonicalKind
    occurred_at: datetime
    action: str = Field(min_length=1, max_length=64, description="Normalized verb, e.g. 'connected_to'.")
    outcome: str | None = Field(default=None, max_length=32)
    actor: EntityRef | None = Field(default=None, description="Entity that initiated the event.")
    target: EntityRef | None = Field(default=None, description="Entity acted upon.")
    entities: list[EntityRef] = Field(default_factory=list, max_length=64)
    raw_event_id: UUID = Field(description="The telemetry.raw event this was derived from (lineage).")
    raw_event_type: EventType
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Normalized flat attributes (ports, bytes, query name, …)."
    )
    enrichment: dict[str, Any] = Field(
        default_factory=dict,
        description="Enrichment results keyed by provider, each carrying its own provenance and "
        "freshness. Absent or partial when a provider was unavailable.",
    )

    @field_validator("occurred_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)

    @model_validator(mode="after")
    def _actor_and_target_in_entities(self) -> CanonicalEventPayload:
        refs = {(e.kind, e.value) for e in self.entities}
        for role, ref in (("actor", self.actor), ("target", self.target)):
            if ref is not None and (ref.kind, ref.value) not in refs:
                raise ValueError(f"{role} must also appear in `entities`")
        return self


TELEMETRY_PAYLOADS: dict[EventType, type[SmBaseModel]] = {
    EventType.telemetry_network_flow: NetworkFlowPayload,
    EventType.telemetry_auth_event: AuthEventPayload,
    EventType.telemetry_dns_query: DnsQueryPayload,
    EventType.telemetry_process_exec: ProcessExecPayload,
    EventType.telemetry_file_access: FileAccessPayload,
    EventType.event_canonical: CanonicalEventPayload,
}
"""The Phase-2 additions to `EVENT_PAYLOAD_REGISTRY`."""

# Register on import so any consumer that has imported `sm_contracts.telemetry`
# can resolve these `event_type`s through the shared registry.
EVENT_PAYLOAD_REGISTRY.update(TELEMETRY_PAYLOADS)
