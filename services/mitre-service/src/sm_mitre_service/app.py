"""mitre-service application factory.

Consumes `detections` (group `mitre-mapping`), writes `technique_mapping`, and
serves the internal MITRE API. Health / metrics + the query API HTTP surface; no
ingest. The lifespan owns the DB pool, the Kafka consumer, and one background
consumer task.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.config import AppSettings, load_settings
from sm_common.db import Database
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing

from .catalog import CatalogRepository
from .deps import Services
from .engine import MappingHandler
from .mapping import MappingEngine
from .metrics import MitreMetrics
from .routes import health, metrics, mitre
from .topics import DETECTIONS_TOPIC
from .version import DEFAULT_CONSUMER_GROUP, SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.mitre_service")


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    mitre_metrics = MitreMetrics(base_metrics, SERVICE_NAME)
    db = Database.from_settings(settings)
    catalog = CatalogRepository(db)
    mapping = MappingEngine(catalog, db)
    group = settings.kafka_consumer_group or DEFAULT_CONSUMER_GROUP
    consumer = EventBusConsumer.from_settings(
        settings, topics=[DETECTIONS_TOPIC], group_id=group, metrics=base_metrics
    )
    handler = MappingHandler(engine=mapping, metrics=mitre_metrics)
    # RecordProcessor needs a producer for the DLQ; mitre-service produces nothing
    # else, so one bare producer is enough.
    producer = EventBusProducer.from_settings(settings, metrics=base_metrics)
    processor = RecordProcessor(
        producer=producer, consumer_group=group, handle=handler.handle,
        metrics=base_metrics, service_name=SERVICE_NAME,
        max_attempts=settings.kafka_handler_max_attempts,
    )
    return Services(
        settings=settings, metrics=base_metrics, mitre_metrics=mitre_metrics, db=db,
        catalog=catalog, mapping=mapping, producer=producer, consumer=consumer, processor=processor,
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

        task: asyncio.Task[None] | None = None
        if owns:
            await svc.producer.start()
            await svc.consumer.start()
            task = asyncio.create_task(svc.consumer.run(svc.processor))
        _log.info("service_start", service=SERVICE_NAME, version=SERVICE_VERSION,
                  consumer_group=svc.consumer.group_id)
        try:
            yield
        finally:
            if owns:
                svc.consumer.request_stop()
                if task is not None:
                    grace = resolved_settings.kafka_shutdown_grace_ms / 1000
                    try:
                        await asyncio.wait_for(task, timeout=grace)
                    except TimeoutError:
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                await svc.consumer.stop()
                await svc.producer.stop()
                await svc.db.dispose()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh MITRE Service",
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
    app.include_router(mitre.router)
    return app
