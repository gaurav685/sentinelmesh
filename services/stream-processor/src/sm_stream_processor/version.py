"""Service version and API version."""

from __future__ import annotations

SERVICE_NAME = "stream-processor"
SERVICE_VERSION = "0.1.0"
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

PRODUCER = f"{SERVICE_NAME}@{SERVICE_VERSION}"
DEFAULT_CONSUMER_GROUP = "stream-processor"
