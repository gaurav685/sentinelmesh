"""`POST /api/v1/sim/scenarios/run` — run a synthetic attack scenario.

Internal-JWT only. The scenario runs against `sm_ml.scenario`'s synthetic
environment — never a real system. A spec naming a non-synthetic or unknown
target is refused (422), not executed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_common.errors import ValidationFailed
from sm_common.security import InternalPrincipal
from sm_contracts import RunScenarioRequest, ScenarioRunResult

from ..deps import Services, get_principal, get_services
from ..scenarios import IsolationRefusedError, run_and_maybe_feed
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/sim", tags=["simulation"])


@router.post("/scenarios/run", response_model=ScenarioRunResult)
async def run_scenario(
    req: RunScenarioRequest,
    principal: InternalPrincipal = Depends(get_principal),
    services: Services = Depends(get_services),
) -> ScenarioRunResult:
    if req.feed_pipeline and services.producer is None:
        raise ValidationFailed(
            "feed_pipeline requires the event bus, which is disabled on this deployment"
        )
    try:
        result = await run_and_maybe_feed(req, principal.tenant_id, services.producer)
    except IsolationRefusedError as exc:
        services.sim_metrics.refused()
        raise ValidationFailed(str(exc)) from exc
    services.sim_metrics.run(kind=req.kind, fed_pipeline=result.fed_to_pipeline)
    return result
