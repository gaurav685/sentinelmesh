"""Liveness, readiness, build metadata.

`/readyz` probes PostgreSQL, the Kafka consumer, and the Kafka producer (all
required — the service both reads `attack_chains` and writes
`campaign.updates`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from sm_common.observability import DependencyCheck, evaluate_readiness, liveness, probe_check
from sm_contracts import HealthResponse, MetaResponse, ReadyResponse

from ..deps import Services, get_services
from ..version import API_PREFIX, SERVICE_NAME, SERVICE_VERSION

__all__ = ["router"]

router = APIRouter(tags=["health"])


def _checks(services: Services) -> list[DependencyCheck]:
    return [
        probe_check("postgres", services.db, required=True),
        probe_check("kafka_consumer", services.consumer, required=True),
        probe_check("kafka_producer", services.producer, required=True),
    ]


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return liveness(SERVICE_NAME, SERVICE_VERSION)


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(response: Response, services: Services = Depends(get_services)) -> ReadyResponse:
    result = await evaluate_readiness(_checks(services))
    for dep in result.dependencies:
        services.metrics.dependency_up.labels(SERVICE_NAME, dep.name).set(1 if dep.healthy else 0)
    if not result.ready:
        response.status_code = 503
    return result


@router.get(f"{API_PREFIX}/meta", response_model=MetaResponse)
async def meta(services: Services = Depends(get_services)) -> MetaResponse:
    return MetaResponse(
        api_version=API_PREFIX.rsplit("/", 1)[-1],
        service=SERVICE_NAME,
        build=SERVICE_VERSION,
        environment=services.settings.env.value,
    )
