"""Kafka topics this service reads and writes.

Names come from the contract registry (`sm_contracts.topics`) so this service
cannot address a topic the catalog does not define.
"""

from __future__ import annotations

from sm_contracts import EventType, dlq_topic, topic_for_event_type

RAW_TOPIC = topic_for_event_type(EventType.telemetry_network_flow)  # all telemetry.* -> telemetry.raw
CANONICAL_TOPIC = topic_for_event_type(EventType.event_canonical)
DLQ_TOPIC = dlq_topic(RAW_TOPIC)

__all__ = ["CANONICAL_TOPIC", "DLQ_TOPIC", "RAW_TOPIC"]
