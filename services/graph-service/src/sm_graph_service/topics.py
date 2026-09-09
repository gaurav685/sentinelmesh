"""Topics this service reads and writes (from the contract registry)."""

from __future__ import annotations

from sm_contracts import EventType, dlq_topic, topic_for_event_type

COMMANDS_TOPIC = topic_for_event_type(EventType.graph_command)
EVENTS_TOPIC = topic_for_event_type(EventType.graph_event)
DLQ_TOPIC = dlq_topic(COMMANDS_TOPIC)

__all__ = ["COMMANDS_TOPIC", "DLQ_TOPIC", "EVENTS_TOPIC"]
