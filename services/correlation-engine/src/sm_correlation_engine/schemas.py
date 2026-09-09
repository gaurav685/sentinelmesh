"""correlation-engine API models (DRAFT — Phase 7, service-local)."""

from __future__ import annotations

from pydantic import BaseModel

from sm_contracts import AttackChainModel

__all__ = ["ChainListResponse"]


class ChainListResponse(BaseModel):
    count: int
    chains: list[AttackChainModel]
