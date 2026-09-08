"""Health, readiness, dependency detail and API metadata.

- `/healthz` — liveness. Never touches a dependency, so a database outage does
  not get the process killed.
- `/readyz` — readiness. Probes the required dependencies and returns **503**
  when any of them is down, so the orchestrator stops routing traffic here.
- `/health/deps` — the same detail, permission-gated for operators.
- `/api/v1/meta` — non-sensitive build info.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from sm_common.observability import (
    DependencyCheck,
    evaluate_readiness,
    liveness,
    probe_check,
)
from sm_contracts import HealthResponse, MetaResponse, ReadyResponse
from sm_contracts.enums import PermissionCode

from ..deps import Services, get_services, require_permission
from ..version import API_PREFIX, SERVICE_NAME, SERVICE_VERSION

__all__ = ["router"]

router = APIRouter(tags=["health"])


def _checks(services: Services) -> list[DependencyCheck]:
    return [
        probe_check("postgres", services.db, required=True),
        probe_check("redis", services.cache, required=True),
    ]


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return liveness(SERVICE_NAME, SERVICE_VERSION)


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(
    response: Response, services: Services = Depends(get_services)
) -> ReadyResponse:
    result = await evaluate_readiness(_checks(services))
    for dep in result.dependencies:
        services.metrics.dependency_up.labels(SERVICE_NAME, dep.name).set(
            1 if dep.healthy else 0
        )
    if not result.ready:
        response.status_code = 503
    return result


@router.get(
    "/health/deps",
    response_model=ReadyResponse,
    dependencies=[Depends(require_permission(PermissionCode.ops_read))],
)
async def health_deps(services: Services = Depends(get_services)) -> ReadyResponse:
    return await evaluate_readiness(_checks(services))


@router.get(f"{API_PREFIX}/meta", response_model=MetaResponse)
async def meta(services: Services = Depends(get_services)) -> MetaResponse:
    return MetaResponse(
        api_version=API_PREFIX.rsplit("/", 1)[-1],
        service=SERVICE_NAME,
        build=SERVICE_VERSION,
        environment=services.settings.env.value,
    )
