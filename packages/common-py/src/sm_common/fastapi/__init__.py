"""FastAPI wiring shared by every SentinelMesh service."""

from __future__ import annotations

from .clientinfo import client_ip, resolve_client_ip
from .exception_handlers import install_exception_handlers
from .hardening import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    build_cors_kwargs,
)
from .metrics_middleware import MetricsMiddleware
from .middleware import RequestContextMiddleware
from .ratelimit import RateLimitMiddleware
from .tracing import TracingMiddleware

__all__ = [
    "BodySizeLimitMiddleware",
    "MetricsMiddleware",
    "RateLimitMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
    "TracingMiddleware",
    "build_cors_kwargs",
    "client_ip",
    "install_exception_handlers",
    "resolve_client_ip",
]
