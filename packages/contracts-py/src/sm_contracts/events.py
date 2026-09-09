"""Canonical event envelope (docs/CONTRACTS.md §2, docs/architecture/event-model.md).

Every message on the durable bus (Kafka) is an `EventEnvelope[PayloadT]`. The
envelope is STABLE; individual payload models are registered in
`EVENT_PAYLOAD_REGISTRY` and are DRAFT until their producing phase ships.

Delivery is at-least-once. `event_id` is the global idempotency key — consumers
must be idempotent on it. Ordering holds only within a partition
(`partition_key`), never globally. Exactly-once is not provided.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .common import SmBaseModel, to_utc

__all__ = [
    "EVENT_PAYLOAD_REGISTRY",
    "EventEnvelope",
    "EventSource",
    "EventType",
    "SourceType",
    "UserEventAction",
    "UserEventPayload",
    "make_partition_key",
]

_PRODUCER_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}@\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_MAX_CLOCK_SKEW = timedelta(minutes=5)


def make_partition_key(tenant_id: str | UUID, primary_entity: str) -> str:
    """The canonical `partition_key` derivation (event-model.md §2):
    `sha256(tenant_id + ':' + primary_entity)[:16]`. Every producer uses this so
    events for one entity land on one partition and stay ordered."""
    primary = primary_entity or "unknown"
    return hashlib.sha256(f"{tenant_id}:{primary}".encode()).hexdigest()[:16]


class SourceType(StrEnum):
    sensor = "sensor"
    deception = "deception"
    simulation = "simulation"
    internal = "internal"


class EventType(StrEnum):
    # telemetry (Phase 2)
    telemetry_network_flow = "telemetry.network_flow"
    telemetry_auth_event = "telemetry.auth_event"
    telemetry_dns_query = "telemetry.dns_query"
    telemetry_process_exec = "telemetry.process_exec"
    telemetry_file_access = "telemetry.file_access"
    # normalized (Phase 2)
    event_canonical = "event.canonical"
    # graph / detection (Phase 3)
    graph_command = "graph.command"
    detection_raised = "detection.raised"
    attack_chain_updated = "attack_chain.updated"
    ti_indicator_updated = "ti.indicator_updated"
    # agents / response (Phase 7)
    agent_task = "agent.task"
    response_action = "response.action"
    # memory (Phase 6)
    campaign_updated = "campaign.updated"
    # reporting (Phase 8)
    report_generated = "report.generated"
    # control plane (Phase 1)
    user_event = "user.event"


class EventSource(SmBaseModel):
    type: SourceType
    sensor_id: UUID | None = None
    site: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _sensor_id_only_for_sensor(self) -> EventSource:
        if self.sensor_id is not None and self.type is not SourceType.sensor:
            raise ValueError("sensor_id is only valid when source.type == 'sensor'")
        return self


PayloadT = TypeVar("PayloadT", bound=SmBaseModel)


class EventEnvelope(SmBaseModel, Generic[PayloadT]):
    event_id: UUID = Field(description="Globally unique, time-ordered (UUIDv7). Idempotency key.")
    event_type: EventType
    event_version: int = Field(ge=1, description="Schema version of `payload`.")
    occurred_at: datetime = Field(description="Event time, from the source. UTC.")
    ingested_at: datetime = Field(description="Set by ingestion-gateway on receipt. UTC.")
    producer: str = Field(description="`<service>@<semver>`, e.g. ingestion-gateway@0.1.0")
    tenant_id: UUID = Field(description="Set from the authenticated producer context, never trusted from input.")
    source: EventSource
    correlation_id: UUID
    trace_id: str | None = Field(default=None, max_length=64, description="W3C trace-context trace-id.")
    partition_key: str = Field(
        min_length=1,
        max_length=128,
        description="Derived (tenant + primary entity). Controls ordering.",
    )
    payload: PayloadT
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-authoritative annotations (enrichment provenance, tags).",
    )

    @field_validator("occurred_at", "ingested_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)

    @field_validator("producer")
    @classmethod
    def _producer_format(cls, v: str) -> str:
        if not _PRODUCER_RE.match(v):
            raise ValueError("producer must be '<service>@<semver>' (e.g. 'graph-service@1.2.0')")
        return v

    @model_validator(mode="after")
    def _time_sanity(self) -> EventEnvelope[PayloadT]:
        # A source cannot emit from the future beyond small clock skew. occurred_at
        # may legitimately be much older than ingested_at (buffered / late data).
        if self.occurred_at > self.ingested_at + _MAX_CLOCK_SKEW:
            raise ValueError("occurred_at is implausibly ahead of ingested_at (> 5m clock skew)")
        return self


# --------------------------------------------------------------------------- #
# Phase 1 payload: user.event
# --------------------------------------------------------------------------- #
class UserEventAction(StrEnum):
    created = "created"
    updated = "updated"
    disabled = "disabled"
    role_granted = "role_granted"
    role_revoked = "role_revoked"
    login_succeeded = "login_succeeded"
    login_failed = "login_failed"
    logged_out = "logged_out"


class UserEventPayload(SmBaseModel):
    action: UserEventAction
    user_id: UUID
    actor_id: UUID | None = Field(
        default=None, description="Who performed the action; null for self-service/system."
    )
    role_id: UUID | None = Field(default=None, description="Set for role_granted / role_revoked.")

    @model_validator(mode="after")
    def _role_id_present_for_role_actions(self) -> UserEventPayload:
        role_actions = {UserEventAction.role_granted, UserEventAction.role_revoked}
        if self.action in role_actions and self.role_id is None:
            raise ValueError(f"role_id is required for action '{self.action.value}'")
        return self


EVENT_PAYLOAD_REGISTRY: dict[EventType, type[SmBaseModel]] = {
    EventType.user_event: UserEventPayload,
}
"""Maps an `event_type` to its payload model. Grows one entry per phase as
payloads are implemented. Consumers use this to pick the concrete
`EventEnvelope[...]` to validate against.

Phase 2's telemetry payloads register themselves here on import of
`sm_contracts.telemetry` (see the bottom of that module) so this module does not
take a dependency on it."""
