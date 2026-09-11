"""A minimal internal client: fetch one full attack chain from
`correlation-engine` (the `attack_chains` topic event is a thin projection
with no `technique_ids` — the full chain is only available from the owning
service's read API)."""

from __future__ import annotations

from uuid import UUID

import httpx

from sm_common.errors import DependencyUnavailable
from sm_common.security import mint_internal_token
from sm_contracts import AttackChainModel

__all__ = ["ChainsClient"]

_SUBJECT = "memory-service"
_AUDIENCE = "correlation-engine"


class ChainsClient:
    def __init__(self, http: httpx.AsyncClient, *, base_url: str, signing_key: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._key = signing_key

    async def get_chain(self, tenant_id: UUID, chain_id: UUID) -> AttackChainModel | None:
        token = mint_internal_token(
            signing_key=self._key, subject=_SUBJECT, tenant_id=tenant_id, audience=_AUDIENCE,
        )
        try:
            resp = await self._http.get(
                f"{self._base_url}/api/v1/chains/{chain_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(f"correlation-engine unreachable: {exc}") from exc
        return AttackChainModel.model_validate(resp.json())
