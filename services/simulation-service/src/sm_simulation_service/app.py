"""simulation-service application factory.

Runs synthetic attack scenarios against `sm_ml`'s digital-twin / scenario
engine and hosts the deception decoy registry. Postgres for decoys +
interactions; an optional Kafka producer (only used when a scenario explicitly
asks to feed the pipeline). No consumer — this service originates work, it does
not react to the bus.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sm_common.bus import EventBusProducer
from sm_common.config import AppSettings, load_settings
from sm_common.db import Database
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing

from .deps import Services
from .metrics import SimulationMetrics
from .repository import DecoyRepository
from .routes import deception, health, metrics, scenarios
from .version import SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.simulation_service")


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    db = Database.from_settings(settings)
    producer = EventBusProducer.from_settings(settings) if settings.event_bus_enabled else None
    return Services(
        settings=settings,
        metrics=base_metrics,
        sim_metrics=SimulationMetrics(base_metrics, SERVICE_NAME),
        db=db,
        decoy_repo=DecoyRepository(db),
        producer=producer,
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
        svc = services or build_services(resolved_settings)
        app.state.services = svc
        if owns and svc.producer is not None:
            await svc.producer.start()
        _log.info(
            "service_start", service=SERVICE_NAME, version=SERVICE_VERSION,
            event_bus=resolved_settings.event_bus_enabled,
        )
        try:
            yield
        finally:
            if owns:
                if svc.producer is not None:
                    await svc.producer.stop()
                await svc.db.dispose()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh Simulation Service",
        version=SERVICE_VERSION,
        lifespan=lifespan,
        docs_url=None if resolved_settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=resolved_settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(scenarios.router)
    app.include_router(deception.router)
    return app
