"""Topics this service reads and writes (from the contract registry)."""

from __future__ import annotations

from sm_contracts import EventType, dlq_topic, topic_for_event_type

CHAINS_TOPIC = topic_for_event_type(EventType.attack_chain_updated)
DLQ_TOPIC = dlq_topic(CHAINS_TOPIC)
CAMPAIGN_UPDATES_TOPIC = topic_for_event_type(EventType.campaign_updated)

__all__ = ["CAMPAIGN_UPDATES_TOPIC", "CHAINS_TOPIC", "DLQ_TOPIC"]
