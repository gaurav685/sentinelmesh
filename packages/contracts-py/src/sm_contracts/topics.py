"""Kafka topic catalog — the definitive registry (Phase 3; event-model.md §3).

The topic taxonomy is a **contract**: every producer and consumer in the mesh
addresses topics through `TOPICS` / `topic_for_event_type`, never a string
literal. Partition counts, keys, retention and consumer groups are recorded here
so the schema, the code and the deployment cannot drift.

Versioned event types
---------------------
An `event_type` string *is* the version identifier (event-model.md §2):

- Payload changes that stay backward-compatible within a major version (add
  optional fields only) do **not** change `event_type`; `event_version` (int on
  the envelope) is bumped.
- A breaking change adds a **new** `EventType` member with a `.v2` suffix and a
  new `TOPICS` / mapping entry; both versions run in parallel during migration.

Today every event type is at v1 (`EVENT_TYPE_VERSION`), so no member carries a
suffix. The first `.v2` will.

Topic provisioning (partition counts) is infrastructure, not contract — see
`sm_common.bus.admin.ensure_topics`, which reads these specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .events import EventType

__all__ = [
    "EVENT_TYPE_TOPIC",
    "EVENT_TYPE_VERSION",
    "TOPICS",
    "TopicSpec",
    "dlq_topic",
    "replay_group",
    "topic_for_event_type",
]

Cleanup = Literal["delete", "compact"]


@dataclass(frozen=True)
class TopicSpec:
    name: str
    partitions: int
    key: str
    """Human description of the partition key, e.g. 'tenant+entity'. The actual
    record key is always `EventEnvelope.partition_key` (`make_partition_key`)."""
    retention: str
    """`<n>d` for time retention, or 'compact' for log-compacted topics."""
    cleanup: Cleanup
    producers: tuple[str, ...]
    consumer_groups: tuple[str, ...]
    has_dlq: bool = True
    partitions_min: int = field(default=1)
    """Never scale a topic *below* this — `partition_key` distribution shifts."""

    @property
    def retention_ms(self) -> int | None:
        if self.retention == "compact":
            return None
        return int(self.retention.rstrip("d")) * 86_400_000


def dlq_topic(topic: str) -> str:
    """`<topic>.dlq` — same partitioning as the source (event-model.md §5)."""
    return f"{topic}.dlq"


def replay_group(group_id: str) -> str:
    """`<group>-replay` — a dedicated group for offset-reset reprocessing with
    side-effecting adapters disabled (event-model.md §6)."""
    return f"{group_id}-replay"


# --------------------------------------------------------------------------- #
# the catalog (event-model.md §3)
# --------------------------------------------------------------------------- #
def _spec(
    name: str, partitions: int, key: str, retention: str, cleanup: Cleanup,
    producers: tuple[str, ...], consumer_groups: tuple[str, ...], *, has_dlq: bool = True,
) -> TopicSpec:
    return TopicSpec(
        name=name, partitions=partitions, key=key, retention=retention, cleanup=cleanup,
        producers=producers, consumer_groups=consumer_groups, has_dlq=has_dlq,
        partitions_min=partitions,
    )


TOPICS: dict[str, TopicSpec] = {
    t.name: t
    for t in (
        _spec("telemetry.raw", 12, "tenant+sensor", "7d", "delete",
              ("ingestion-gateway", "simulation-service"), ("normalization",)),
        _spec("events.canonical", 24, "tenant+entity", "30d", "delete",
              ("normalization-engine",),
              ("stream-processor", "graph-writer", "detection", "memory", "api-projection")),
        _spec("graph.commands", 12, "tenant+entity", "7d", "delete",
              ("stream-processor", "detection-engine", "correlation-engine"), ("graph-writer",)),
        _spec("graph.events", 12, "tenant+entity", "7d", "delete",
              ("graph-service",), ("api-projection", "notification-fanout")),
        _spec("detections", 12, "tenant", "90d", "delete",
              ("detection-engine",),
              ("correlation", "mitre-mapping", "api-projection", "ai-analyst", "agent-orchestrator",
               "memory", "reporting", "notification-fanout")),
        _spec("attack_chains", 6, "tenant", "180d", "delete",
              ("correlation-engine",),
              ("graph-writer", "mitre-mapping", "ai-analyst", "memory", "reporting")),
        _spec("ti.updates", 3, "source", "compact", "compact",
              ("threat-intel-service",), ("normalization", "detection")),
        _spec("agent.tasks", 6, "tenant", "30d", "delete",
              ("agent-orchestrator", "ai-analyst-service"), ("agent-workers",)),
        _spec("response.actions", 6, "tenant", "365d", "delete",
              ("agent-orchestrator",), ("audit-sink", "api-projection")),
        _spec("campaign.updates", 3, "tenant", "180d", "delete",
              ("memory-service",), ("ai-analyst", "reporting")),
        _spec("report.generated", 3, "tenant", "90d", "delete",
              ("reporting-service",), ("api-projection", "notification-fanout")),
        _spec("user.events", 3, "tenant", "90d", "compact",
              ("api-gateway",), ("audit-sink",), has_dlq=False),
    )
}


# --------------------------------------------------------------------------- #
# event_type -> topic  (only the types that exist today)
# --------------------------------------------------------------------------- #
EVENT_TYPE_TOPIC: dict[EventType, str] = {
    EventType.telemetry_network_flow: "telemetry.raw",
    EventType.telemetry_auth_event: "telemetry.raw",
    EventType.telemetry_dns_query: "telemetry.raw",
    EventType.telemetry_process_exec: "telemetry.raw",
    EventType.telemetry_file_access: "telemetry.raw",
    EventType.event_canonical: "events.canonical",
    EventType.graph_command: "graph.commands",
    EventType.graph_event: "graph.events",
    EventType.detection_raised: "detections",
    EventType.attack_chain_updated: "attack_chains",
    EventType.ti_indicator_updated: "ti.updates",
    EventType.agent_task: "agent.tasks",
    EventType.response_action: "response.actions",
    EventType.campaign_updated: "campaign.updates",
    EventType.report_generated: "report.generated",
    EventType.user_event: "user.events",
}

EVENT_TYPE_VERSION: dict[EventType, int] = dict.fromkeys(EventType, 1)
"""Major schema version per event type. A `.v2` member gets its own entry."""


def topic_for_event_type(event_type: EventType) -> str:
    try:
        return EVENT_TYPE_TOPIC[event_type]
    except KeyError:  # pragma: no cover - guards an unmapped new member
        raise KeyError(f"no topic mapped for event_type {event_type!r}") from None
