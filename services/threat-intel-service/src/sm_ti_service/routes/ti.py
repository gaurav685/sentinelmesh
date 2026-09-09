"""Internal threat-intel API (service-JWT, audience `threat-intel-service`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from sm_common.errors import ValidationFailed
from sm_common.security import InternalPrincipal
from sm_contracts import IndicatorType, TiSourceKind

from ..deps import Services, get_principal, get_repo, get_services
from ..publish import publish_update
from ..schemas import (
    EnrichRequest,
    EnrichResponse,
    IndicatorsResponse,
    SubmitIndicatorRequest,
    SubmitIndicatorResponse,
)
from ..store import IndicatorInput, IndicatorRepository
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/ti", tags=["threat-intel"])


@router.post("/enrich", response_model=EnrichResponse)
async def enrich(
    req: EnrichRequest,
    principal: InternalPrincipal = Depends(get_principal),
    repo: IndicatorRepository = Depends(get_repo),
    services: Services = Depends(get_services),
) -> EnrichResponse:
    results = await repo.enrich(
        principal.tenant_id, [(i.type, i.value) for i in req.items]
    )
    for r in results:
        services.ti_metrics.enrich(
            "hit" if r.matched else ("expired" if r.freshness else "miss")
        )
    return EnrichResponse(results=results)


@router.get("/indicators", response_model=IndicatorsResponse)
async def indicators(
    type: IndicatorType | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    principal: InternalPrincipal = Depends(get_principal),
    repo: IndicatorRepository = Depends(get_repo),
) -> IndicatorsResponse:
    rows = await repo.list_indicators(principal.tenant_id, indicator_type=type, limit=limit)
    return IndicatorsResponse(count=len(rows), indicators=rows)


@router.post("/indicators", response_model=SubmitIndicatorResponse, status_code=201)
async def submit_indicator(
    req: SubmitIndicatorRequest,
    principal: InternalPrincipal = Depends(get_principal),
    repo: IndicatorRepository = Depends(get_repo),
    services: Services = Depends(get_services),
) -> SubmitIndicatorResponse:
    try:
        indicator, action = await repo.upsert(IndicatorInput(
            type=req.type, value=req.value, source=f"tenant:{principal.subject}",
            source_kind=TiSourceKind.manual, confidence=req.confidence, tags=req.tags,
            actor_id=req.actor_id, reference=req.reference, tenant_id=principal.tenant_id,
            expires_at=req.expires_at,
        ))
    except ValueError as exc:
        raise ValidationFailed(f"invalid {req.type.value} indicator: {exc}") from exc
    services.ti_metrics.upsert(action.value)
    await publish_update(services.producer, indicator, action)
    return SubmitIndicatorResponse(indicator=indicator, action=action)
