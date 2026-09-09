"""Ingestion gateway application factory.

Middleware order (outermost first):

1. `RequestContextMiddleware` — request/correlation ids for every log line and
   error body.
2. `SecurityHeadersMiddleware`.
3. `RateLimitMiddleware(fail_open=False)` — a limiter-store outage **rejects**
   (503). Ingestion must not let an unbounded flood through when Redis is down.
4. `BodySizeLimitMiddleware` — an oversized payload is refused before routing.

There is no CORS middleware: sensors are not browsers.

`create_app` accepts a pre-built `Services` so tests substitute in-memory sinks,
a fake Redis and (optionally) a real database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sm_common.cache import Cache
from sm_common.config import AppSettings, load_settings
from sm_common.db import Database
from sm_common.fastapi import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing
from sm_common.security import SensorAuth

from .dedup import Dedup
from .deps import Services
from .metrics import IngestionMetrics
from .routes import health, ingest, metrics
from .sinks import LoggingDeadLetterSink, LoggingRawEventSink
from .version import SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.ingestion_gateway")


def build_services(settings: AppSettings) -> Services:
    db = Database.from_settings(settings)
    cache = Cache.from_settings(settings)
    base_metrics = build_metrics(SERVICE_NAME)
    return Services(
        settings=settings,
        db=db,
        cache=cache,
        metrics=base_metrics,
        ingest_metrics=IngestionMetrics(base_metrics, SERVICE_NAME),
        sensor_auth=SensorAuth(),
        raw_sink=LoggingRawEventSink(),
        dlq_sink=LoggingDeadLetterSink(),
        dedup=Dedup(
            cache.client,
            ttl_seconds=settings.ingest_dedup_ttl_seconds,
            key_prefix=settings.redis_key_prefix,
        ),
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
        resolved_services = services or build_services(resolved_settings)
        app.state.services = resolved_services
        app.state.rate_limit_redis = resolved_services.cache.client
        app.state.rate_limit_metrics = resolved_services.metrics
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
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh Ingestion Gateway",
        version=SERVICE_VERSION,
        lifespan=lifespan,
        docs_url=None if resolved_settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/openapi.json",
    )

    # Registered bottom-up; see the module docstring for the effective order.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=resolved_settings.http_max_body_bytes)
    app.add_middleware(RateLimitMiddleware, settings=resolved_settings, fail_open=False)
    app.add_middleware(SecurityHeadersMiddleware, hsts=resolved_settings.is_production)
    app.add_middleware(RequestContextMiddleware)

    install_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(ingest.router)

    return app
