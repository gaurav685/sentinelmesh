"""SentinelMesh MITRE ATT&CK service (req 7).

A versioned technique / tactic catalog imported offline from a STIX 2.1 bundle
(`scripts/import_attack_stix.py`) — **no ATT&CK data ships in this repository**.
A rule-based mapping engine validates the candidate technique ids a detection
rule named against the imported catalog: unknown ids are reported `unmapped`,
never guessed. `AttackMatrixVersion` records exactly what an import produced, and
no coverage is claimed beyond it. LLM-assisted mapping is allowed via the `/map`
API (`MappingSource.llm`) but is never authoritative alone (ADR-014).

Consumes `detections` (group `mitre-mapping`); writes `technique_mapping`; serves
`GET /api/v1/mitre/{techniques,heatmap}` and `POST /api/v1/mitre/map`.
"""

from __future__ import annotations

from .app import build_services, create_app
from .version import API_PREFIX, API_VERSION, SERVICE_NAME, SERVICE_VERSION

__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "build_services",
    "create_app",
]
