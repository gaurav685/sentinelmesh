"""Durable event bus (Kafka / Redpanda; ADR-008).

Kafka is the **only** durable, ordered transport between services. Redis is not
the bus (ADR-009). This package holds the thin producer and consumer wrappers every service uses.
"""

from __future__ import annotations

from .consumer import EventBusConsumer, dlq_payload
from .producer import EventBusProducer

__all__ = ["EventBusConsumer", "EventBusProducer", "dlq_payload"]
