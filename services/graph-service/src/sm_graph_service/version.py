"""Service version and API version."""

from __future__ import annotations

SERVICE_NAME = "graph-service"
SERVICE_VERSION = "0.1.0"
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

PRODUCER = f"{SERVICE_NAME}@{SERVICE_VERSION}"
# The command topic's only consumer group (event-model.md §3).
DEFAULT_CONSUMER_GROUP = "graph-writer"
