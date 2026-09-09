"""Threat-intel enrichment: tag a canonical event's entities against
`threat-intel-service`.

- Looks up IPs, domains and file hashes present on the event.
- Adds `enrichment["threat_intel"]` with a `provider`, an `as_of` timestamp, and
  a `matches` list (only genuine, non-expired hits — never fabricated). A miss
  leaves the key absent.
- Any failure (TI-service unreachable / slow / error) returns `{}` — the runner
  records the provider as unavailable and the event is **not** failed (R2).
- Enrichment runs before a tenant context exists, so it queries the platform
  (global) indicator scope only; tenant-submitted IOCs are re-checked downstream
  by `detection-engine`.
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import Any

import httpx
import structlog

from sm_common.clock import utcnow
from sm_common.security import mint_internal_token
from sm_contracts import CanonicalEventPayload, EntityKind, IndicatorType

__all__ = ["ThreatIntelEnricher"]

_log = structlog.get_logger("sm.normalization.enrich.ti")
_HASH_RE_LEN = {32: IndicatorType.md5, 40: IndicatorType.sha1, 64: IndicatorType.sha256}
_PLATFORM_TENANT = uuid.UUID(int=0)


class ThreatIntelEnricher:
    name = "threat_intel"

    def __init__(
        self, http: httpx.AsyncClient, *, base_url: str, signing_key: str, timeout_s: float
    ) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._signing_key = signing_key
        self._timeout = timeout_s

    def _lookups(self, payload: CanonicalEventPayload) -> list[dict[str, str]]:
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, str]] = []

        def _add(itype: IndicatorType, value: str) -> None:
            key = (itype.value, value)
            if key not in seen:
                seen.add(key)
                out.append({"type": itype.value, "value": value})

        for e in payload.entities:
            if e.kind is EntityKind.ip:
                try:
                    addr = ipaddress.ip_address(e.value)
                except ValueError:
                    continue
                _add(IndicatorType.ipv4 if addr.version == 4 else IndicatorType.ipv6, e.value)
            elif e.kind is EntityKind.domain:
                _add(IndicatorType.domain, e.value)

        raw_hash = payload.attributes.get("hash_sha256")
        if isinstance(raw_hash, str) and len(raw_hash) in _HASH_RE_LEN:
            _add(_HASH_RE_LEN[len(raw_hash)], raw_hash)
        return out

    async def enrich(self, payload: CanonicalEventPayload) -> dict[str, Any]:
        items = self._lookups(payload)
        if not items:
            return {}
        token = mint_internal_token(
            signing_key=self._signing_key, subject="normalization-engine",
            tenant_id=_PLATFORM_TENANT, audience="threat-intel-service",
        )
        try:
            resp = await self._http.post(
                f"{self._base}/api/v1/ti/enrich",
                json={"items": items},
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            _log.info("ti_enrich_unavailable", error=str(exc))
            return {}

        results = resp.json().get("results", [])
        matches = [
            {
                "type": r["type"], "value": r["value"],
                "confidence": (r.get("indicator") or {}).get("confidence"),
                "reputation": (r.get("indicator") or {}).get("reputation"),
                "source": (r.get("indicator") or {}).get("source"),
                "freshness": r.get("freshness"),
            }
            for r in results
            if r.get("matched")
        ]
        if not matches:
            return {}
        return {
            "threat_intel": {
                "provider": "threat-intel-service",
                "as_of": utcnow().isoformat(),
                "matches": matches,
            }
        }
