"""Client for `ml-inference` (`POST /api/v1/infer/{model}`).

A trained-model contribution is *optional*. Any failure — connection error,
timeout, HTTP 503 `MODEL_UNAVAILABLE`, an unexpected status — returns `None`, and
`detection-engine` sets `scoring_status = DEGRADED` and scores on the statistical
detector alone (ADR-013). This client never raises into the handler.
"""

from __future__ import annotations

import httpx
import structlog

from sm_common.security import mint_internal_token
from sm_contracts import AnomalyMethod, CanonicalKind
from sm_ml import FEATURE_SCHEMA_VERSION
from sm_ml.models import AnomalyScore

__all__ = ["MODEL_FOR_KIND", "InferenceClient"]

_log = structlog.get_logger("sm.detection_engine.inference")

# The registered model name detection-engine asks for, per canonical kind. Absent
# from the registry -> MODEL_UNAVAILABLE -> degraded. `ml-training` registers
# these names when a dataset run produces them.
MODEL_FOR_KIND: dict[CanonicalKind, str] = {
    CanonicalKind.network_flow: "isolation_forest_network_flow",
    CanonicalKind.process_exec: "isolation_forest_process_exec",
    CanonicalKind.dns: "isolation_forest_dns",
    CanonicalKind.auth: "isolation_forest_auth",
    CanonicalKind.file_access: "isolation_forest_file_access",
}


class InferenceClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str,
        signing_key: str,
        timeout_s: float,
    ) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._signing_key = signing_key
        self._timeout = timeout_s

    def _token(self, tenant_id: str) -> str:
        import uuid

        return mint_internal_token(
            signing_key=self._signing_key,
            subject="detection-engine",
            tenant_id=uuid.UUID(tenant_id),
            audience="ml-inference",
        )

    async def score(
        self, tenant_id: str, kind: CanonicalKind, features: list[float]
    ) -> AnomalyScore | None:
        model = MODEL_FOR_KIND.get(kind)
        if model is None:
            return None
        try:
            resp = await self._http.post(
                f"{self._base}/api/v1/infer/{model}",
                json={
                    "kind": kind.value,
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "features": features,
                },
                headers={"Authorization": f"Bearer {self._token(tenant_id)}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            _log.info("inference_unreachable", model=model, error=str(exc))
            return None
        if resp.status_code != 200:
            _log.info("inference_unavailable", model=model, status=resp.status_code)
            return None
        body = resp.json()
        return AnomalyScore(
            method=AnomalyMethod(body["method"]),
            score=float(body["score"]),
            normalized_score=float(body["normalized_score"]),
            threshold=float(body["threshold"]),
            is_anomaly=bool(body["is_anomaly"]),
            model_version=body.get("model_version"),
            contributing_features=list(body.get("contributing_features", [])),
        )
