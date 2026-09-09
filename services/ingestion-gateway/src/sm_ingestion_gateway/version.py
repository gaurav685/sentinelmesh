"""Service version and API version."""

from __future__ import annotations

SERVICE_NAME = "ingestion-gateway"
SERVICE_VERSION = "0.1.0"
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

PRODUCER = f"{SERVICE_NAME}@{SERVICE_VERSION}"
"""The `producer` stamped on every envelope this service builds
(`<service>@<semver>`, matched by the envelope's producer regex)."""
