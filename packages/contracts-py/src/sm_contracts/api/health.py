from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..common import SmBaseModel

__all__ = ["DepStatus", "HealthResponse", "MetaResponse", "ReadyResponse"]


class HealthResponse(SmBaseModel):
    """`GET /healthz` — liveness. The process is up and can serve."""

    status: Literal["ok"] = "ok"
    service: str
    version: str


class DepStatus(SmBaseModel):
    name: str
    healthy: bool
    detail: str | None = Field(default=None, max_length=300, description="No secrets, no internals.")
    latency_ms: float | None = Field(default=None, ge=0)


class ReadyResponse(SmBaseModel):
    """`GET /readyz` — readiness. `ready` is false if any *required* dependency
    is unreachable; the service should then be pulled from rotation."""

    ready: bool
    dependencies: list[DepStatus] = Field(default_factory=list)


class MetaResponse(SmBaseModel):
    """`GET /api/v1/meta` — non-sensitive build/runtime info."""

    api_version: str
    service: str
    build: str
    environment: Literal["local", "ci", "staging", "production"]
