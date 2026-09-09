"""Topics this service reads and writes (from the contract registry)."""

from __future__ import annotations

from sm_contracts import EventType, dlq_topic, topic_for_event_type

DETECTIONS_TOPIC = topic_for_event_type(EventType.detection_raised)
DLQ_TOPIC = dlq_topic(DETECTIONS_TOPIC)
CHAINS_TOPIC = topic_for_event_type(EventType.attack_chain_updated)
GRAPH_COMMANDS_TOPIC = topic_for_event_type(EventType.graph_command)

__all__ = ["CHAINS_TOPIC", "DETECTIONS_TOPIC", "DLQ_TOPIC", "GRAPH_COMMANDS_TOPIC"]
