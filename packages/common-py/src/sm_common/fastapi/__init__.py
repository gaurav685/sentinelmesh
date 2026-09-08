"""FastAPI wiring shared by every SentinelMesh service."""

from __future__ import annotations

from .exception_handlers import install_exception_handlers
from .hardening import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    build_cors_kwargs,
)
from .middleware import RequestContextMiddleware

__all__ = [
    "BodySizeLimitMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
    "build_cors_kwargs",
    "install_exception_handlers",
]
