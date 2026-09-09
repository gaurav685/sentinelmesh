"""Service version and API version."""

from __future__ import annotations

SERVICE_NAME = "normalization-engine"
SERVICE_VERSION = "0.1.0"
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

PRODUCER = f"{SERVICE_NAME}@{SERVICE_VERSION}"
"""The `producer` stamped on every `events.canonical` envelope this service
emits (`<service>@<semver>`, matched by the envelope's producer regex)."""

DEFAULT_CONSUMER_GROUP = "normalization"
"""Consumer group when `SM_KAFKA_CONSUMER_GROUP` is unset (event-model.md §3)."""
