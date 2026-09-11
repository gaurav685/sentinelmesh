"""Deception decoy registry.

Every decoy declares an isolated `network_boundary` — `'production'` is not a
schema-legal value, so a request for it is a 422 before any handler runs.
Teardown is idempotent; interaction history survives it (audit). Internal-JWT
only; the tenant is always the verified token's, never a request field.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sm_common.errors import NotFound
from sm_common.security import InternalPrincipal
from sm_contracts import Decoy, DecoyInteraction, DecoyInteractionIn, RegisterDecoyRequest

from ..deps import Services, get_decoy_repository, get_principal, get_services
from ..repository import DecoyRepository
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/deception", tags=["deception"])


@router.post("/decoys", response_model=Decoy)
async def register_decoy(
    req: RegisterDecoyRequest,
    principal: InternalPrincipal = Depends(get_principal),
    repo: DecoyRepository = Depends(get_decoy_repository),
    services: Services = Depends(get_services),
) -> Decoy:
    decoy = await repo.register(principal.tenant_id, req)
    services.sim_metrics.decoy("registered")
    return decoy


@router.get("/decoys", response_model=list[Decoy])
async def list_decoys(
    status: str | None = Query(default=None),
    principal: InternalPrincipal = Depends(get_principal),
    repo: DecoyRepository = Depends(get_decoy_repository),
) -> list[Decoy]:
    return await repo.list_decoys(principal.tenant_id, status=status)


@router.get("/decoys/{decoy_id}", response_model=Decoy)
async def get_decoy(
    decoy_id: UUID,
    principal: InternalPrincipal = Depends(get_principal),
    repo: DecoyRepository = Depends(get_decoy_repository),
) -> Decoy:
    found = await repo.get(principal.tenant_id, decoy_id)
    if found is None:
        raise NotFound("decoy not found")
    return found


@router.delete("/decoys/{decoy_id}", response_model=Decoy)
async def teardown_decoy(
    decoy_id: UUID,
    principal: InternalPrincipal = Depends(get_principal),
    repo: DecoyRepository = Depends(get_decoy_repository),
    services: Services = Depends(get_services),
) -> Decoy:
    """Idempotent: tearing down an already-torn-down decoy just returns it."""
    found = await repo.teardown(principal.tenant_id, decoy_id)
    if found is None:
        raise NotFound("decoy not found")
    services.sim_metrics.decoy("torn_down")
    return found


@router.post("/decoys/{decoy_id}/interactions", response_model=DecoyInteraction)
async def capture_interaction(
    decoy_id: UUID,
    req: DecoyInteractionIn,
    principal: InternalPrincipal = Depends(get_principal),
    repo: DecoyRepository = Depends(get_decoy_repository),
    services: Services = Depends(get_services),
) -> DecoyInteraction:
    """Attacker-supplied `source` / `detail` are captured for telemetry only —
    never trusted, never executed. A torn-down decoy captures nothing further."""
    result = await repo.record_interaction(principal.tenant_id, decoy_id, req)
    if result is None:
        raise NotFound("decoy not found or no longer active")
    services.sim_metrics.decoy("interaction")
    return result


@router.get("/decoys/{decoy_id}/interactions", response_model=list[DecoyInteraction])
async def list_interactions(
    decoy_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
    principal: InternalPrincipal = Depends(get_principal),
    repo: DecoyRepository = Depends(get_decoy_repository),
) -> list[DecoyInteraction]:
    return await repo.list_interactions(principal.tenant_id, decoy_id, limit=limit)
