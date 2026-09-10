"""`POST /api/v1/agents/run` — run a named defense agent over supplied evidence.

Internal-JWT only (audience `ai-analyst`). The agent works from the evidence in
the request; it holds no standing permissions and cannot execute anything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_common.security import InternalPrincipal
from sm_contracts import AgentRunRequest, AgentRunResult

from ..agents import AgentRunner
from ..deps import Services, get_agent_runner, get_principal, get_services
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/agents", tags=["agents"])


@router.post("/run", response_model=AgentRunResult)
async def run(
    req: AgentRunRequest,
    principal: InternalPrincipal = Depends(get_principal),
    runner: AgentRunner = Depends(get_agent_runner),
    services: Services = Depends(get_services),
) -> AgentRunResult:
    result = await runner.run(req, tenant_id=principal.tenant_id)
    services.analyst_metrics.observed(
        task=f"agent:{req.agent}", degraded=result.status != "completed", confidence="low"
    )
    return result
