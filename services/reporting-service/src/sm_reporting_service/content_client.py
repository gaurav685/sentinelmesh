"""Internal-service clients for the content services `reporting-service`
gathers a report from (service-catalog: `graph-service`, `mitre-service`,
`ai-analyst`, `memory-service`; `detection-engine` is read directly from
Postgres — see `content_repository.py`).

Mirrors `api-gateway`'s `InternalServiceClient`: each call mints a
short-lived service token scoped to the target's audience and the
tenant the report is being generated for. Any transport failure or
non-2xx is `DependencyUnavailable` — the caller marks that section
`missing`, it never fabricates content in its place (Constitution §3).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from sm_common.errors import DependencyUnavailable
from sm_common.security import mint_internal_token

__all__ = ["ContentClient"]

_SUBJECT = "reporting-service"

#: `ThreatSubjectType` value -> graph node label. Mirrors the local mapping
#: `graph-service`'s own `hunt.py` uses for the same purpose.
SUBJECT_TYPE_LABEL: dict[str, str] = {
    "identity": "Identity",
    "host": "Host",
    "ip": "IpAddress",
    "domain": "Domain",
    "detection": "Detection",
}
#: The inverse, restricted to labels that map back onto a `ThreatSubjectType`
#: (used to turn a graph neighbor into a `ReportAsset`).
LABEL_SUBJECT_TYPE: dict[str, str] = {v: k for k, v in SUBJECT_TYPE_LABEL.items()}


class ContentClient:
    def __init__(
        self, http: httpx.AsyncClient, *, signing_key: str,
        graph_url: str, mitre_url: str, ai_analyst_url: str, memory_url: str,
    ) -> None:
        self._http = http
        self._key = signing_key
        self._urls = {
            "graph-service": graph_url.rstrip("/"),
            "mitre-service": mitre_url.rstrip("/"),
            "ai-analyst": ai_analyst_url.rstrip("/"),
            "memory-service": memory_url.rstrip("/"),
        }

    def _token(self, audience: str, tenant_id: UUID) -> str:
        return mint_internal_token(
            signing_key=self._key, subject=_SUBJECT, tenant_id=tenant_id, audience=audience,
        )

    async def _get(
        self, audience: str, path: str, tenant_id: UUID, *, params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request(audience, "GET", path, tenant_id, params=params)

    async def _post(self, audience: str, path: str, tenant_id: UUID, *, json: Any) -> Any:
        return await self._request(audience, "POST", path, tenant_id, json=json)

    async def _request(
        self, audience: str, method: str, path: str, tenant_id: UUID, *,
        params: dict[str, Any] | None = None, json: Any | None = None,
    ) -> Any:
        url = f"{self._urls[audience]}{path}"
        headers = {"Authorization": f"Bearer {self._token(audience, tenant_id)}"}
        try:
            resp = await self._http.request(method, url, params=params, json=json, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise DependencyUnavailable(f"{audience} returned {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(f"{audience} unreachable: {exc}") from exc
        return resp.json()

    # ---- graph-service -----------------------------------------------
    async def graph_neighbors(
        self, tenant_id: UUID, *, label: str, key: str, depth: int = 1,
    ) -> dict[str, Any] | None:
        result: dict[str, Any] | None = await self._get(
            "graph-service", "/api/v1/graph/neighbors", tenant_id,
            params={"label": label, "key": key, "depth": depth},
        )
        return result

    # ---- mitre-service -------------------------------------------------
    async def mitre_techniques(self, tenant_id: UUID) -> list[dict[str, Any]]:
        result = await self._get("mitre-service", "/api/v1/mitre/techniques", tenant_id)
        return result or []

    # ---- ai-analyst ---------------------------------------------------
    async def explain(self, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any] | None:
        result: dict[str, Any] | None = await self._post(
            "ai-analyst", "/api/v1/analyst/explain", tenant_id, json=payload
        )
        return result

    # ---- memory-service -------------------------------------------------
    async def memory_patterns(
        self, tenant_id: UUID, *, subject_type: str, subject_id: str,
    ) -> list[dict[str, Any]]:
        result = await self._get(
            "memory-service", "/api/v1/memory/patterns", tenant_id,
            params={"subject_type": subject_type, "subject_id": subject_id},
        )
        return result or []

    async def predict_lateral_movement(
        self, tenant_id: UUID, *, subject_type: str, subject_id: str,
    ) -> dict[str, Any] | None:
        result: dict[str, Any] | None = await self._post(
            "memory-service", "/api/v1/predict/lateral-movement", tenant_id,
            json={"subject_type": subject_type, "subject_id": subject_id},
        )
        return result
