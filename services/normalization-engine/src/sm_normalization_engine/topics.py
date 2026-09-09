"""Kafka topics this service reads and writes (event-model.md §3)."""

from __future__ import annotations

RAW_TOPIC = "telemetry.raw"
CANONICAL_TOPIC = "events.canonical"
DLQ_TOPIC = "telemetry.raw.dlq"

__all__ = ["CANONICAL_TOPIC", "DLQ_TOPIC", "RAW_TOPIC"]
