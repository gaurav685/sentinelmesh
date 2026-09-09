"""Topics this service reads (from the contract registry)."""

from __future__ import annotations

from sm_contracts import EventType, dlq_topic, topic_for_event_type

DETECTIONS_TOPIC = topic_for_event_type(EventType.detection_raised)
CHAINS_TOPIC = topic_for_event_type(EventType.attack_chain_updated)
DLQ_TOPIC = dlq_topic(DETECTIONS_TOPIC)

__all__ = ["CHAINS_TOPIC", "DETECTIONS_TOPIC", "DLQ_TOPIC"]
