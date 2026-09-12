"""threat-intel-service application factory.

HTTP surface (health / metrics + the IOC / enrichment API) plus one background
task: the expiry sweep. The lifespan owns the DB pool, the Kafka producer, and
the sweeper.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI

from sm_common.bus import EventBusProducer
from sm_common.config import AppSettings, load_settings
from sm_common.db import Database
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    TracingMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing

from .deps import Services
from .metrics import TiMetrics
from .poller import ProviderPoller
from .providers import build_providers
from .routes import health, metrics, ti
from .scheduler import ExpirySweeper
from .store import IndicatorRepository
from .version import SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.ti_service")


def build_services(settings: AppSettings, *, http: httpx.AsyncClient) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    ti_metrics = TiMetrics(base_metrics, SERVICE_NAME)
    db = Database.from_settings(settings)
    repo = IndicatorRepository(db, default_ttl_seconds=settings.ti_default_ttl_seconds)
    producer = EventBusProducer.from_settings(settings, metrics=base_metrics)
    sweeper = ExpirySweeper(
        repo=repo, producer=producer, metrics=ti_metrics,
        interval_seconds=settings.ti_expiry_sweep_seconds,
    )
    poller = ProviderPoller(
        providers=build_providers(settings, http, ti_metrics),
        repo=repo, db=db, producer=producer, metrics=ti_metrics,
        interval_seconds=settings.ti_poll_seconds,
        default_ttl_seconds=settings.ti_default_ttl_seconds,
    )
    return Services(
        settings=settings, metrics=base_metrics, ti_metrics=ti_metrics, db=db,
        repo=repo, producer=producer, sweeper=sweeper, poller=poller,
    )


def create_app(
    settings: AppSettings | None = None, services: Services | None = None
) -> FastAPI:
    resolved_settings = settings or (services.settings if services else load_settings())
    configure_logging(resolved_settings)
    configure_tracing(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns = services is None
        http: httpx.AsyncClient | None = None
        if owns:
            http = httpx.AsyncClient(timeout=resolved_settings.ti_http_timeout_s)
            svc = build_services(resolved_settings, http=http)
        else:
            assert services is not None
            svc = services
        app.state.services = svc

        tasks: list[asyncio.Task[None]] = []
        if owns:
            await svc.producer.start()
            tasks.append(asyncio.create_task(svc.sweeper.run()))
            tasks.append(asyncio.create_task(svc.poller.run()))
        _log.info("service_start", service=SERVICE_NAME, version=SERVICE_VERSION)
        try:
            yield
        finally:
            if owns:
                svc.sweeper.stop()
                svc.poller.stop()
                for task in tasks:
                    with suppress(TimeoutError, asyncio.CancelledError):
                        await asyncio.wait_for(task, timeout=5)
                await svc.producer.stop()
                await svc.db.dispose()
                if http is not None:
                    await http.aclose()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh Threat Intel Service",
        version=SERVICE_VERSION,
        lifespan=lifespan,
        docs_url=None if resolved_settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=resolved_settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TracingMiddleware)
    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(ti.router)
    return app
