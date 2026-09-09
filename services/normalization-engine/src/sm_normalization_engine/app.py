"""Normalization-engine application factory.

The engine is a stream processor with a small HTTP surface for health / metrics.
The lifespan owns the Kafka producer, the Kafka consumer, and one background task
running the consume loop (`EventBusConsumer.run(engine.handle)`). Shutdown stops
the consumer (which breaks the loop), cancels the task, then stops the producer.

`create_app` accepts a pre-built `Services` so tests can substitute fakes and
still exercise the real routing / readiness.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from sm_common.bus import EventBusConsumer, EventBusProducer
from sm_common.config import AppSettings, load_settings
from sm_common.fastapi import RequestContextMiddleware, SecurityHeadersMiddleware, install_exception_handlers
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing

from .deps import Services
from .engine import NormalizationEngine
from .metrics import NormalizationMetrics
from .routes import health, metrics
from .topics import RAW_TOPIC
from .version import DEFAULT_CONSUMER_GROUP, SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.normalization_engine")


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    norm_metrics = NormalizationMetrics(base_metrics, SERVICE_NAME)
    producer = EventBusProducer.from_settings(settings)
    group = settings.kafka_consumer_group or DEFAULT_CONSUMER_GROUP
    consumer = EventBusConsumer.from_settings(settings, topics=[RAW_TOPIC], group_id=group)
    engine = NormalizationEngine(
        producer=producer, consumer_group=group, metrics=base_metrics, norm_metrics=norm_metrics
    )
    return Services(
        settings=settings, metrics=base_metrics, norm_metrics=norm_metrics,
        producer=producer, consumer=consumer, engine=engine,
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
            task = asyncio.create_task(svc.consumer.run(svc.engine.handle))
        _log.info("service_start", service=SERVICE_NAME, version=SERVICE_VERSION,
                  consumer_group=svc.consumer.group_id)
        try:
            yield
        finally:
            if owns:
                await svc.consumer.stop()
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                await svc.producer.stop()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh Normalization Engine",
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
    return app
