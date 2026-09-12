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

import httpx
from fastapi import FastAPI

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.config import AppSettings, load_settings
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    TracingMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing

from .deps import Services
from .engine import NormalizationEngine
from .enrich import Enricher
from .enrich.threat_intel import ThreatIntelEnricher
from .metrics import NormalizationMetrics
from .routes import health, metrics
from .topics import RAW_TOPIC
from .version import DEFAULT_CONSUMER_GROUP, SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.normalization_engine")


def build_services(settings: AppSettings, *, http: httpx.AsyncClient | None = None) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    norm_metrics = NormalizationMetrics(base_metrics, SERVICE_NAME)
    producer = EventBusProducer.from_settings(settings, metrics=base_metrics)
    group = settings.kafka_consumer_group or DEFAULT_CONSUMER_GROUP
    consumer = EventBusConsumer.from_settings(
        settings, topics=[RAW_TOPIC], group_id=group, metrics=base_metrics
    )
    enrichers: tuple[Enricher, ...] = ()
    if settings.ti_enrichment_enabled and http is not None:
        enrichers = (ThreatIntelEnricher(
            http, base_url=settings.ti_service_url,
            signing_key=settings.internal_jwt_signing_key.get_secret_value(),
            timeout_s=settings.ti_http_timeout_s,
        ),)
    engine = NormalizationEngine(
        producer=producer, consumer_group=group, metrics=base_metrics, norm_metrics=norm_metrics,
        enrichers=enrichers,
    )
    processor = RecordProcessor(
        producer=producer, consumer_group=group, handle=engine.handle,
        metrics=base_metrics, service_name=SERVICE_NAME,
        max_attempts=settings.kafka_handler_max_attempts,
    )
    return Services(
        settings=settings, metrics=base_metrics, norm_metrics=norm_metrics,
        producer=producer, consumer=consumer, engine=engine, processor=processor,
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
                # Graceful: let the in-flight batch finish + commit, then close.
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
                if http is not None:
                    await http.aclose()
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
    app.add_middleware(TracingMiddleware)
    install_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(metrics.router)
    return app
