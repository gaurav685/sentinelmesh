"""API gateway application factory.

Middleware order (outermost first) is deliberate:

1. `RequestContextMiddleware` — request/correlation ids exist for every log line
   and error body, including ones produced by the layers below it.
2. `CORSMiddleware` — preflight is answered before any work is done.
3. `SecurityHeadersMiddleware` — headers are added to every response.
4. `BodySizeLimitMiddleware` — an oversized body is rejected before routing.

Starlette applies `add_middleware` in reverse, so they are registered bottom-up.

`create_app` accepts a pre-built `Services` so tests can substitute in-memory
collaborators and still exercise the real routing, authentication, authorization
and error handling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sm_common.audit import AuditWriter
from sm_common.cache import Cache
from sm_common.config import AppSettings, load_settings
from sm_common.db import Database
from sm_common.fastapi import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    build_cors_kwargs,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing
from sm_common.security import OidcClient

from .deps import Services, SqlRepositoryFactory
from .routes import admin, auth, health
from .security.session import RedisOidcStateStore, RedisSessionStore
from .version import SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.api_gateway")


def build_services(settings: AppSettings) -> Services:
    """Construct the real, infrastructure-backed collaborators."""
    db = Database.from_settings(settings)
    cache = Cache.from_settings(settings)
    http = httpx.AsyncClient(timeout=settings.llm_request_timeout_s)
    oidc = OidcClient.from_settings(settings, http)
    return Services(
        settings=settings,
        db=db,
        cache=cache,
        sessions=RedisSessionStore(
            cache,
            idle_seconds=settings.session_idle_seconds,
            absolute_seconds=settings.session_absolute_seconds,
        ),
        oidc_states=RedisOidcStateStore(cache, ttl_seconds=settings.oidc_state_ttl_seconds),
        metrics=build_metrics(SERVICE_NAME),
        audit=AuditWriter(),
        repositories=SqlRepositoryFactory(),
        http=http,
        oidc=oidc,
    )


def create_app(
    settings: AppSettings | None = None, services: Services | None = None
) -> FastAPI:
    resolved_settings = settings or (services.settings if services else load_settings())
    configure_logging(resolved_settings)
    configure_tracing(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_services = services is None
        app.state.services = services or build_services(resolved_settings)
        _log.info(
            "service_start",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            profile=resolved_settings.deployment_profile,
        )
        try:
            yield
        finally:
            if owns_services:
                built: Services = app.state.services
                await built.db.dispose()
                await built.cache.close()
                if built.http is not None:
                    await built.http.aclose()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh API Gateway",
        version=SERVICE_VERSION,
        lifespan=lifespan,
        # Interactive docs are useful in development but are not exposed in
        # production, where the OpenAPI document is served to authorized tooling
        # only.
        docs_url=None if resolved_settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/openapi.json",
    )

    # Registered bottom-up; see the module docstring for the effective order.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=resolved_settings.http_max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=resolved_settings.is_production)
    # `build_cors_kwargs` returns a plain mapping; Starlette's `add_middleware`
    # signature cannot be matched against **kwargs by the type checker.
    app.add_middleware(
        CORSMiddleware,
        **build_cors_kwargs(resolved_settings),  # type: ignore[arg-type]
    )
    app.add_middleware(RequestContextMiddleware)

    install_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(auth.me_router)
    app.include_router(admin.router)

    return app
