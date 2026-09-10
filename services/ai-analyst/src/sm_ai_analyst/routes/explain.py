"""`POST /api/v1/analyst/explain` — the grounded analyst.

Internal-JWT only (audience `ai-analyst`); `api-gateway` is the sole caller. The
request carries the evidence `api-gateway` already gathered and tenant-scoped —
the analyst never reads a store itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_common.security import InternalPrincipal
from sm_contracts import ExplainRequest, Explanation

from ..analyst import IncidentAnalyst
from ..deps import Services, get_analyst, get_principal, get_services
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/analyst", tags=["analyst"])


@router.post("/explain", response_model=Explanation)
async def explain(
    req: ExplainRequest,
    principal: InternalPrincipal = Depends(get_principal),
    analyst: IncidentAnalyst = Depends(get_analyst),
    services: Services = Depends(get_services),
) -> Explanation:
    result = await analyst.explain(req)
    services.analyst_metrics.observed(
        task=req.task, degraded=result.degraded, confidence=result.confidence
    )
    if result.evidence_flagged:
        services.analyst_metrics.flagged()
    return result
