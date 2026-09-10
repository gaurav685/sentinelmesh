"""Internal-service clients for the SOC BFF (Phase 9).

`api-gateway` proxies the read APIs of `correlation-engine` (attack chains),
`graph-service` (graph + intel), `threat-intel-service` (indicators / enrichment)
and `mitre-service` (heatmap / catalog). Each call mints a short-lived service
token scoped to the target's audience and the **caller's tenant** — the internal
service re-derives the tenant from that token, so a browser can never widen its
scope.

Any transport failure or non-2xx from a dependency is surfaced as
`DependencyUnavailable` (HTTP 503) — the SOC UI shows an error state, it never
sees a raw 500 or a fabricated result.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from sm_common.errors import DependencyUnavailable
from sm_common.security import mint_internal_token

__all__ = ["InternalServiceClient"]

_SUBJECT = "api-gateway"


class InternalServiceClient:
    def __init__(
        self, http: httpx.AsyncClient, *, signing_key: str, ttl_seconds: int,
        correlation_url: str, graph_url: str, ti_url: str, mitre_url: str,
        ai_analyst_url: str = "http://localhost:8010",
    ) -> None:
        self._http = http
        self._key = signing_key
        self._ttl = ttl_seconds
        self._urls = {
            "correlation-engine": correlation_url.rstrip("/"),
            "graph-service": graph_url.rstrip("/"),
            "threat-intel-service": ti_url.rstrip("/"),
            "mitre-service": mitre_url.rstrip("/"),
            "ai-analyst": ai_analyst_url.rstrip("/"),
        }

    def _token(self, audience: str, tenant_id: UUID) -> str:
        return mint_internal_token(
            signing_key=self._key, subject=_SUBJECT, tenant_id=tenant_id,
            audience=audience, ttl_seconds=self._ttl,
        )

    async def _request(
        self, audience: str, method: str, path: str, tenant_id: UUID, *,
        params: dict[str, Any] | None = None, json: Any | None = None,
    ) -> Any:
        url = f"{self._urls[audience]}{path}"
        headers = {"Authorization": f"Bearer {self._token(audience, tenant_id)}"}
        try:
            resp = await self._http.request(
                method, url, params=params, json=json, headers=headers,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise DependencyUnavailable(f"{audience} returned {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(f"{audience} unreachable: {exc}") from exc
        return resp.json()

    # ---- correlation-engine: attack chains -----------------------
    async def chains(self, tenant_id: UUID, **query: Any) -> Any:
        return await self._request(
            "correlation-engine", "GET", "/api/v1/chains", tenant_id,
            params={k: v for k, v in query.items() if v is not None},
        )

    async def chain(self, tenant_id: UUID, chain_id: str) -> Any:
        return await self._request(
            "correlation-engine", "GET", f"/api/v1/chains/{chain_id}", tenant_id
        )

    # ---- graph-service ---------------------------------------
    async def graph_neighbors(self, tenant_id: UUID, *, label: str, key: str, depth: int) -> Any:
        return await self._request(
            "graph-service", "GET", "/api/v1/graph/neighbors", tenant_id,
            params={"label": label, "key": key, "depth": depth},
        )

    async def graph_paths(
        self, tenant_id: UUID, *, src_label: str, src_key: str, dst_label: str, dst_key: str,
        max_depth: int,
    ) -> Any:
        return await self._request(
            "graph-service", "GET", "/api/v1/graph/paths", tenant_id,
            params={
                "src_label": src_label, "src_key": src_key, "dst_label": dst_label,
                "dst_key": dst_key, "max_depth": max_depth,
            },
        )

    async def graph_intel(self, tenant_id: UUID, *, label: str, key: str, depth: int) -> Any:
        return await self._request(
            "graph-service", "GET", "/api/v1/graph/intel", tenant_id,
            params={"label": label, "key": key, "depth": depth},
        )

    # ---- threat-intel-service --------------------------------
    async def ti_indicators(self, tenant_id: UUID, **query: Any) -> Any:
        return await self._request(
            "threat-intel-service", "GET", "/api/v1/ti/indicators", tenant_id,
            params={k: v for k, v in query.items() if v is not None},
        )

    async def ti_enrich(self, tenant_id: UUID, items: list[dict[str, str]]) -> Any:
        return await self._request(
            "threat-intel-service", "POST", "/api/v1/ti/enrich", tenant_id, json={"items": items},
        )

    # ---- mitre-service ---------------------------------------
    async def mitre_heatmap(self, tenant_id: UUID) -> Any:
        return await self._request("mitre-service", "GET", "/api/v1/mitre/heatmap", tenant_id)

    async def mitre_techniques(self, tenant_id: UUID) -> Any:
        return await self._request("mitre-service", "GET", "/api/v1/mitre/techniques", tenant_id)

    # ---- ai-analyst -----------------------------------------
    async def explain(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "ai-analyst", "POST", "/api/v1/analyst/explain", tenant_id, json=payload
        )
