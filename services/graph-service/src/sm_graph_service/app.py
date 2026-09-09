"""graph-service application factory.

The write path into Neo4j: consume `graph.commands`, apply each command as a
parameterized idempotent MERGE, emit `graph.events`. The lifespan owns the Neo4j
driver, the Kafka producer, the Kafka consumer, and one background task running
`EventBusConsumer.run(RecordProcessor)`. Graceful shutdown: `request_stop()`
lets the in-flight batch commit, then the clients close.

No HTTP ingest — the only routes are health and metrics. The read-query API is
Phase 4 Unit 3.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.config import AppSettings, load_settings
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_exception_handlers,
)
from sm_common.graph import Graph, GraphUnavailableError
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing

from .deps import Services
from .engine import GraphEngine
from .metrics import GraphMetrics
from .routes import health, metrics
from .topics import COMMANDS_TOPIC
from .version import DEFAULT_CONSUMER_GROUP, SERVICE_NAME, SERVICE_VERSION
from .writer import GraphWriter

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.graph_service")


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    graph_metrics = GraphMetrics(base_metrics, SERVICE_NAME)
    graph = Graph.from_settings(settings)
    producer = EventBusProducer.from_settings(settings, metrics=base_metrics)
    group = settings.kafka_consumer_group or DEFAULT_CONSUMER_GROUP
    consumer = EventBusConsumer.from_settings(
        settings, topics=[COMMANDS_TOPIC], group_id=group, metrics=base_metrics
    )
    engine = GraphEngine(
        writer=GraphWriter(graph), producer=producer,
        metrics=base_metrics, graph_metrics=graph_metrics,
    )
    processor = RecordProcessor(
        producer=producer, consumer_group=group, handle=engine.handle,
        metrics=base_metrics, service_name=SERVICE_NAME,
        max_attempts=settings.kafka_handler_max_attempts,
    )
    return Services(
        settings=settings, metrics=base_metrics, graph_metrics=graph_metrics,
        graph=graph, producer=producer, consumer=consumer,
        engine=engine, processor=processor,
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
            # A missing graph must not crash startup — /readyz reports it and the
            # consumer's TransientError path retries until Neo4j is back.
            with suppress(GraphUnavailableError):
                await svc.graph.start()
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
                await svc.graph.close()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh Graph Service",
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
