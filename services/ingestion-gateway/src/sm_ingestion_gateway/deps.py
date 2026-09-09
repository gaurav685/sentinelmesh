"""Dependency wiring for the ingestion gateway.

`Services` is built once at startup and read from `app.state`. `get_sensor`
is the only place a sensor identity is produced: it reads the `Authorization`
header and resolves it against the `sensor` table on every request (nothing
about identity or tenant is taken from the request body).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from sm_common.cache import Cache
from sm_common.config import AppSettings
from sm_common.db import Database
from sm_common.errors import Unauthenticated
from sm_common.observability import Metrics
from sm_common.security import SensorAuth, SensorIdentity

from .dedup import Dedup
from .metrics import IngestionMetrics
from .pipeline import IngestContext
from .sinks import DeadLetterSink, RawEventSink

__all__ = [
    "Services",
    "get_ingest_context",
    "get_sensor",
    "get_services",
]


@dataclass
class Services:
    settings: AppSettings
    db: Database
    cache: Cache
    metrics: Metrics
    ingest_metrics: IngestionMetrics
    sensor_auth: SensorAuth
    raw_sink: RawEventSink
    dlq_sink: DeadLetterSink
    dedup: Dedup


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_ingest_context(services: Services = Depends(get_services)) -> IngestContext:
    return IngestContext(
        raw_sink=services.raw_sink,
        dlq_sink=services.dlq_sink,
        dedup=services.dedup,
        metrics=services.ingest_metrics,
    )


async def get_sensor(
    request: Request, services: Services = Depends(get_services)
) -> SensorIdentity:
    presented = request.headers.get("authorization", "")
    if not presented:
        services.metrics.authn_failures.labels(
            services.settings.service_name, "no_authorization_header"
        ).inc()
        raise Unauthenticated()

    try:
        # A transaction: SensorAuth touches `last_seen_at` (throttled) and that
        # write must commit with the lookup.
        async with services.db.transaction() as session:
            identity = await services.sensor_auth.authenticate(
                session, presented_credential=presented
            )
    except Unauthenticated:
        services.metrics.authn_failures.labels(
            services.settings.service_name, "sensor_auth_failed"
        ).inc()
        raise

    return identity
