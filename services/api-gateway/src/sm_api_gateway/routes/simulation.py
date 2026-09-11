"""Simulation + deception BFF (Phase 12) — the browser-facing proxy for
`simulation-service`.

Every endpoint is behind `require_permission` (deny-by-default, metered +
audited on denial), scopes to `principal.tenant_id` from the session, and
returns a typed `sm_contracts` shape. A transport failure or an unexpected
downstream status is `DependencyUnavailable` (503); an isolation refusal or a
`feed_pipeline` request with no event bus is `ValidationFailed` (422) — the
dependency understood the request and rejected it, this is not an outage.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sm_common.errors import DependencyUnavailable, NotFound
from sm_contracts import (
    BlastRadiusRequest,
    BlastRadiusResult,
    Decoy,
    DecoyInteraction,
    PermissionCode,
    RegisterDecoyRequest,
    RunScenarioRequest,
    ScenarioRunResult,
    TwinSnapshot,
)

from ..clients import InternalServiceClient
from ..deps import get_internal_client, require_permission
from ..security.principal import Principal
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/soc", tags=["simulation"])

_sim = require_permission(PermissionCode.simulation_run)
_deception = require_permission(PermissionCode.deception_manage)


def _require_dict(value: Any, dependency: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DependencyUnavailable(f"{dependency} returned an unexpected response")
    return value


# ---- simulation: scenario runs + digital twin -----------------
@router.post("/simulation/run", response_model=ScenarioRunResult)
async def run_scenario(
    body: RunScenarioRequest,
    principal: Principal = Depends(_sim),
    client: InternalServiceClient = Depends(get_internal_client),
) -> ScenarioRunResult:
    raw = await client.sim_run_scenario(principal.tenant_id, body.model_dump(mode="json"))
    return ScenarioRunResult.model_validate(_require_dict(raw, "simulation-service"))


@router.get("/simulation/twin", response_model=TwinSnapshot)
async def get_twin(
    seed: int = Query(default=1, ge=0),
    principal: Principal = Depends(_sim),
    client: InternalServiceClient = Depends(get_internal_client),
) -> TwinSnapshot:
    raw = await client.sim_twin(principal.tenant_id, seed=seed)
    return TwinSnapshot.model_validate(_require_dict(raw, "simulation-service"))


@router.post("/simulation/blast-radius", response_model=BlastRadiusResult)
async def blast_radius(
    body: BlastRadiusRequest,
    principal: Principal = Depends(_sim),
    client: InternalServiceClient = Depends(get_internal_client),
) -> BlastRadiusResult:
    raw = await client.sim_blast_radius(principal.tenant_id, body.model_dump(mode="json"))
    return BlastRadiusResult.model_validate(_require_dict(raw, "simulation-service"))


# ---- deception: decoy registry --------------------------------
@router.post("/deception/decoys", response_model=Decoy)
async def register_decoy(
    body: RegisterDecoyRequest,
    principal: Principal = Depends(_deception),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Decoy:
    raw = await client.register_decoy(principal.tenant_id, body.model_dump(mode="json"))
    return Decoy.model_validate(_require_dict(raw, "simulation-service"))


@router.get("/deception/decoys", response_model=list[Decoy])
async def list_decoys(
    status: str | None = Query(default=None),
    principal: Principal = Depends(_deception),
    client: InternalServiceClient = Depends(get_internal_client),
) -> list[Decoy]:
    raw = await client.list_decoys(principal.tenant_id, status=status)
    if not isinstance(raw, list):
        raise DependencyUnavailable("simulation-service returned an unexpected response")
    return [Decoy.model_validate(row) for row in raw]


@router.get("/deception/decoys/{decoy_id}", response_model=Decoy)
async def get_decoy(
    decoy_id: UUID,
    principal: Principal = Depends(_deception),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Decoy:
    raw = await client.get_decoy(principal.tenant_id, str(decoy_id))
    if raw is None:
        raise NotFound("decoy not found")
    return Decoy.model_validate(_require_dict(raw, "simulation-service"))


@router.delete("/deception/decoys/{decoy_id}", response_model=Decoy)
async def teardown_decoy(
    decoy_id: UUID,
    principal: Principal = Depends(_deception),
    client: InternalServiceClient = Depends(get_internal_client),
) -> Decoy:
    raw = await client.teardown_decoy(principal.tenant_id, str(decoy_id))
    if raw is None:
        raise NotFound("decoy not found")
    return Decoy.model_validate(_require_dict(raw, "simulation-service"))


@router.get("/deception/decoys/{decoy_id}/interactions", response_model=list[DecoyInteraction])
async def list_decoy_interactions(
    decoy_id: UUID,
    principal: Principal = Depends(_deception),
    client: InternalServiceClient = Depends(get_internal_client),
) -> list[DecoyInteraction]:
    raw = await client.list_decoy_interactions(principal.tenant_id, str(decoy_id))
    if raw is None:
        raise NotFound("decoy not found")
    if not isinstance(raw, list):
        raise DependencyUnavailable("simulation-service returned an unexpected response")
    return [DecoyInteraction.model_validate(row) for row in raw]
