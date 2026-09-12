"""memory-service application factory.

Consumes `attack_chains` (group `memory`), upserts threat-memory patterns /
campaigns / adversary fingerprints, produces `campaign.updates`, and serves
the internal retrieval + similarity API and the predictive-intelligence API
(`sm_ml.predict` — deterministic heuristics, no trained model). The lifespan
owns the DB pool, the HTTP client (to `correlation-engine`), the Kafka
producer + consumer + one background consumer task, and the retention-sweep
background task.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
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

from .chains_client import ChainsClient
from .deps import Services
from .ingest import MemoryIngestHandler
from .metrics import MemoryMetrics
from .repository import MemoryRepository
from .retention import RetentionSweeper
from .routes import health, memory, metrics, prediction
from .topics import CHAINS_TOPIC
from .version import DEFAULT_CONSUMER_GROUP, SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.memory_service")


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    mem_metrics = MemoryMetrics(base_metrics, SERVICE_NAME)
    db = Database.from_settings(settings)
    repo = MemoryRepository(db)
    http = httpx.AsyncClient(timeout=10.0)
    chains = ChainsClient(
        http, base_url=settings.correlation_engine_url,
        signing_key=settings.internal_jwt_signing_key.get_secret_value(),
    )
    group = settings.kafka_consumer_group or DEFAULT_CONSUMER_GROUP
    consumer = EventBusConsumer.from_settings(
        settings, topics=[CHAINS_TOPIC], group_id=group, metrics=base_metrics
    )
    producer = EventBusProducer.from_settings(settings, metrics=base_metrics)
    handler = MemoryIngestHandler(
        repo=repo, chains=chains, producer=producer, metrics=mem_metrics,
        campaign_similarity_threshold=settings.memory_campaign_similarity_threshold,
    )
    processor = RecordProcessor(
        producer=producer, consumer_group=group, handle=handler.handle,
        metrics=base_metrics, service_name=SERVICE_NAME,
        max_attempts=settings.kafka_handler_max_attempts,
    )
    sweeper = RetentionSweeper(
        repo=repo, metrics=mem_metrics, interval_seconds=settings.memory_retention_sweep_seconds,
        dormant_after_days=settings.memory_dormant_after_days,
        close_after_days=settings.memory_close_after_days,
        retention_days=settings.memory_retention_days,
    )
    return Services(
        settings=settings, metrics=base_metrics, mem_metrics=mem_metrics, db=db, repo=repo,
        http=http, chains=chains, producer=producer, consumer=consumer, processor=processor,
        sweeper=sweeper,
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

        consumer_task: asyncio.Task[None] | None = None
        sweeper_task: asyncio.Task[None] | None = None
        if owns:
            await svc.producer.start()
            await svc.consumer.start()
            consumer_task = asyncio.create_task(svc.consumer.run(svc.processor))
            sweeper_task = asyncio.create_task(svc.sweeper.run())
        _log.info(
            "service_start", service=SERVICE_NAME, version=SERVICE_VERSION,
            consumer_group=svc.consumer.group_id,
        )
        try:
            yield
        finally:
            if owns:
                svc.consumer.request_stop()
                svc.sweeper.stop()
                if consumer_task is not None:
                    grace = resolved_settings.kafka_shutdown_grace_ms / 1000
                    try:
                        await asyncio.wait_for(consumer_task, timeout=grace)
                    except TimeoutError:
                        consumer_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await consumer_task
                if sweeper_task is not None:
                    with suppress(asyncio.CancelledError):
                        await asyncio.wait_for(sweeper_task, timeout=1.0)
                await svc.consumer.stop()
                await svc.producer.stop()
                await svc.http.aclose()
                await svc.db.dispose()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh Memory Service",
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
    app.include_router(memory.router)
    app.include_router(prediction.router)
    return app
