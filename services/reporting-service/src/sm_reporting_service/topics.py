"""Topic this service writes (from the contract registry)."""

from __future__ import annotations

from sm_contracts import EventType, topic_for_event_type

REPORT_GENERATED_TOPIC = topic_for_event_type(EventType.report_generated)

__all__ = ["REPORT_GENERATED_TOPIC"]
