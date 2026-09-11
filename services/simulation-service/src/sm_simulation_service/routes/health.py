"""Liveness, readiness, build metadata.

`/readyz` probes PostgreSQL (required for the decoy registry). The event bus is
optional — `feed_pipeline` scenario requests are refused with a clear reason
when it is disabled, so its absence does not make the service unready.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from sm_common.observability import DependencyCheck, evaluate_readiness, liveness, probe_check
from sm_contracts import DepStatus, HealthResponse, MetaResponse, ReadyResponse

from ..deps import Services, get_services
from ..version import API_PREFIX, SERVICE_NAME, SERVICE_VERSION

__all__ = ["router"]

router = APIRouter(tags=["health"])


def _checks(services: Services) -> list[DependencyCheck]:
    return [probe_check("postgres", services.db, required=True)]


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return liveness(SERVICE_NAME, SERVICE_VERSION)


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(response: Response, services: Services = Depends(get_services)) -> ReadyResponse:
    result = await evaluate_readiness(_checks(services))
    for dep in result.dependencies:
        services.metrics.dependency_up.labels(SERVICE_NAME, dep.name).set(1 if dep.healthy else 0)
    result.dependencies.append(
        DepStatus(
            name="event_bus", healthy=True,
            detail="enabled" if services.producer is not None else "disabled (feed_pipeline refused)",
        )
    )
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
