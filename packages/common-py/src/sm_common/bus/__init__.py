"""Durable event bus (Kafka / Redpanda; ADR-008).

Kafka is the **only** durable, ordered transport between services. Redis is not
the bus (ADR-009). This package holds the thin producer wrapper every producing
service uses; consumers arrive with the first consuming service.
"""

from __future__ import annotations

from .producer import EventBusProducer

__all__ = ["EventBusProducer"]
