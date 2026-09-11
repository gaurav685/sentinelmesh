"""Service version and API version."""

from __future__ import annotations

SERVICE_NAME = "reporting-service"
SERVICE_VERSION = "0.1.0"
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
DEFAULT_PORT = 8013

PRODUCER = f"{SERVICE_NAME}@{SERVICE_VERSION}"
