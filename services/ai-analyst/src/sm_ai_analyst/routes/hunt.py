"""NL -> QueryPlan translation, and hunt-result explanation.

Internal-JWT only (audience `ai-analyst`); `api-gateway` is the sole caller. The
LLM only ever produces a `QueryPlan` (parsed into the closed schema) or says the
request is out of scope — it never produces a query.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_common.security import InternalPrincipal
from sm_contracts import HuntExplainRequest, HuntResult, NlHuntRequest, PlanResponse

from ..deps import Services, get_hunt_planner, get_principal, get_services
from ..hunt import HuntPlanner, explain_hunt
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/hunt", tags=["hunt"])


@router.post("/plan", response_model=PlanResponse)
async def plan(
    req: NlHuntRequest,
    _principal: InternalPrincipal = Depends(get_principal),
    planner: HuntPlanner = Depends(get_hunt_planner),
) -> PlanResponse:
    return await planner.plan(req)


@router.post("/explain", response_model=HuntResult)
async def explain(
    req: HuntExplainRequest,
    _principal: InternalPrincipal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> HuntResult:
    text = await explain_hunt(
        services.llm, services.settings.llm_default_model or "unset", req.result
    )
    return req.result.model_copy(update={"explanation": text[:4000]})
