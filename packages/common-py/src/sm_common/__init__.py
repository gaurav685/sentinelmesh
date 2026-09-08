"""SentinelMesh shared platform primitives.

No business logic lives here — only cross-cutting building blocks every service
needs: configuration, logging, error types, ID/time helpers, security
primitives, health checks, and FastAPI wiring.

Unit 1 (this package's first slice) provides everything except the live
infrastructure clients (Postgres engine, Redis client, OIDC client, OTel
exporter, audit writer) — those land in the next Phase-1 unit.
"""

from __future__ import annotations

from .clock import utcnow
from .config import AppSettings, Environment, ResponseMode, load_settings
from .context import get_correlation_id, get_request_id, request_context, set_request_context
from .errors import (
    Conflict,
    DependencyUnavailable,
    InternalError,
    InvalidCredentials,
    NotFound,
    PayloadTooLarge,
    PermissionDenied,
    RateLimited,
    SmError,
    TenantForbidden,
    Unauthenticated,
    UnsupportedMediaType,
    ValidationFailed,
)
from .ids import new_correlation_id, new_request_id, uuid7
from .logging import configure_logging, get_logger
from .redaction import REDACTED, redact

__all__ = [
    "REDACTED",
    "AppSettings",
    "Conflict",
    "DependencyUnavailable",
    "Environment",
    "InternalError",
    "InvalidCredentials",
    "NotFound",
    "PayloadTooLarge",
    "PermissionDenied",
    "RateLimited",
    "ResponseMode",
    "SmError",
    "TenantForbidden",
    "Unauthenticated",
    "UnsupportedMediaType",
    "ValidationFailed",
    "configure_logging",
    "get_correlation_id",
    "get_logger",
    "get_request_id",
    "load_settings",
    "new_correlation_id",
    "new_request_id",
    "redact",
    "request_context",
    "set_request_context",
    "utcnow",
    "uuid7",
]
