"""Topics this service reads and writes (from the contract registry)."""

from __future__ import annotations

from sm_contracts import EventType, dlq_topic, topic_for_event_type

CANONICAL_TOPIC = topic_for_event_type(EventType.event_canonical)
DETECTIONS_TOPIC = topic_for_event_type(EventType.detection_raised)
DLQ_TOPIC = dlq_topic(CANONICAL_TOPIC)

__all__ = ["CANONICAL_TOPIC", "DETECTIONS_TOPIC", "DLQ_TOPIC"]
