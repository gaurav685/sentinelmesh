"""Internal-service clients for the SOC BFF (Phase 9).

`api-gateway` proxies the read APIs of `correlation-engine` (attack chains),
`graph-service` (graph + intel), `threat-intel-service` (indicators / enrichment)
and `mitre-service` (heatmap / catalog). Each call mints a short-lived service
token scoped to the target's audience and the **caller's tenant** — the internal
service re-derives the tenant from that token, so a browser can never widen its
scope.

Any transport failure or non-2xx from a dependency is surfaced as
`DependencyUnavailable` (HTTP 503) — the SOC UI shows an error state, it never
sees a raw 500 or a fabricated result. The one exception is a `422` (the
dependency understood the request and rejected it as invalid — an isolation
refusal, say): that is a real client error, not an outage, so it is re-raised
as `ValidationFailed` with the dependency's own message.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from sm_common.errors import DependencyUnavailable, ValidationFailed
from sm_common.security import mint_internal_token

__all__ = ["InternalServiceClient"]

_SUBJECT = "api-gateway"


class InternalServiceClient:
    def __init__(
        self, http: httpx.AsyncClient, *, signing_key: str, ttl_seconds: int,
        correlation_url: str, graph_url: str, ti_url: str, mitre_url: str,
        ai_analyst_url: str = "http://localhost:8010",
        simulation_url: str = "http://localhost:8011",
        memory_url: str = "http://localhost:8012",
        reporting_url: str = "http://localhost:8013",
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
            "simulation-service": simulation_url.rstrip("/"),
            "memory-service": memory_url.rstrip("/"),
            "reporting-service": reporting_url.rstrip("/"),
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
            if exc.response.status_code == 422:
                message = f"{audience} rejected the request"
                try:
                    message = exc.response.json()["error"]["message"]
                except (ValueError, KeyError, TypeError):
                    pass
                raise ValidationFailed(message) from exc
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

    async def graph_hunt(self, tenant_id: UUID, plan: dict[str, Any]) -> Any:
        return await self._request(
            "graph-service", "POST", "/api/v1/graph/hunt", tenant_id, json=plan
        )

    # ---- ai-analyst: NL hunting -----------------------------
    async def hunt_plan(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request("ai-analyst", "POST", "/api/v1/hunt/plan", tenant_id, json=payload)

    async def hunt_explain(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "ai-analyst", "POST", "/api/v1/hunt/explain", tenant_id, json=payload
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

    # ---- simulation-service: scenarios + digital twin --------
    async def sim_run_scenario(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "simulation-service", "POST", "/api/v1/sim/scenarios/run", tenant_id, json=payload
        )

    async def sim_twin(self, tenant_id: UUID, *, seed: int) -> Any:
        return await self._request(
            "simulation-service", "GET", "/api/v1/sim/twin", tenant_id, params={"seed": seed}
        )

    async def sim_blast_radius(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "simulation-service", "POST", "/api/v1/sim/twin/blast-radius", tenant_id, json=payload
        )

    # ---- simulation-service: deception decoy registry --------
    async def register_decoy(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "simulation-service", "POST", "/api/v1/deception/decoys", tenant_id, json=payload
        )

    async def list_decoys(self, tenant_id: UUID, *, status: str | None = None) -> Any:
        return await self._request(
            "simulation-service", "GET", "/api/v1/deception/decoys", tenant_id,
            params={"status": status} if status else None,
        )

    async def get_decoy(self, tenant_id: UUID, decoy_id: str) -> Any:
        return await self._request(
            "simulation-service", "GET", f"/api/v1/deception/decoys/{decoy_id}", tenant_id
        )

    async def teardown_decoy(self, tenant_id: UUID, decoy_id: str) -> Any:
        return await self._request(
            "simulation-service", "DELETE", f"/api/v1/deception/decoys/{decoy_id}", tenant_id
        )

    async def list_decoy_interactions(self, tenant_id: UUID, decoy_id: str) -> Any:
        return await self._request(
            "simulation-service", "GET", f"/api/v1/deception/decoys/{decoy_id}/interactions", tenant_id
        )

    # ---- memory-service: threat memory -----------------------
    async def mem_similar(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "memory-service", "POST", "/api/v1/memory/similar", tenant_id, json=payload
        )

    async def mem_patterns(
        self, tenant_id: UUID, *, subject_type: str | None = None, subject_id: str | None = None,
    ) -> Any:
        return await self._request(
            "memory-service", "GET", "/api/v1/memory/patterns", tenant_id,
            params={k: v for k, v in {"subject_type": subject_type, "subject_id": subject_id}.items() if v},
        )

    async def mem_fingerprint(self, tenant_id: UUID, subject_type: str, subject_id: str) -> Any:
        return await self._request(
            "memory-service", "GET", f"/api/v1/memory/fingerprints/{subject_type}/{subject_id}",
            tenant_id,
        )

    async def mem_campaigns(self, tenant_id: UUID, *, status: str | None = None) -> Any:
        return await self._request(
            "memory-service", "GET", "/api/v1/memory/campaigns", tenant_id,
            params={"status": status} if status else None,
        )

    async def mem_campaign(self, tenant_id: UUID, campaign_id: str) -> Any:
        return await self._request(
            "memory-service", "GET", f"/api/v1/memory/campaigns/{campaign_id}", tenant_id
        )

    # ---- memory-service: predictive intelligence --------------
    async def predict_attack_progression(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "memory-service", "POST", "/api/v1/predict/attack-progression", tenant_id, json=payload
        )

    async def predict_next_action(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "memory-service", "POST", "/api/v1/predict/next-action", tenant_id, json=payload
        )

    async def predict_lateral_movement(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "memory-service", "POST", "/api/v1/predict/lateral-movement", tenant_id, json=payload
        )

    async def predict_threat_trajectory(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request(
            "memory-service", "POST", "/api/v1/predict/threat-trajectory", tenant_id, json=payload
        )

    # ---- reporting-service ------------------------------------
    async def create_report(self, tenant_id: UUID, payload: dict[str, Any]) -> Any:
        return await self._request("reporting-service", "POST", "/api/v1/reports", tenant_id, json=payload)

    async def get_report(self, tenant_id: UUID, report_id: str) -> Any:
        return await self._request(
            "reporting-service", "GET", f"/api/v1/reports/{report_id}", tenant_id
        )

    # ---- ai-analyst: attack storytelling -----------------------
    async def get_narrative(self, tenant_id: UUID, chain_id: str) -> Any:
        return await self._request(
            "ai-analyst", "GET", f"/api/v1/incidents/{chain_id}/narrative", tenant_id
        )
