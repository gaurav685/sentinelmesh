"""SentinelMesh threat memory (reqs 21, 37).

Consumes `attack_chains`, fetches the full chain from `correlation-engine`
(the topic event is a thin projection with no technique data), and upserts
three distinct record kinds — never a duplicate of the operational/knowledge
graph or the detection/chain tables (`docs/ARCHITECTURE_DECISIONS.md`
ADR-011):

- **`ThreatMemory`** — a behavioral pattern per subject, upserted as its
  technique set grows.
- **`Campaign`** — a set of attack chains judged related by shared
  technique usage (pgvector cosine similarity, exact-match fallback).
- **`AdversaryFingerprint`** — one evolving fingerprint per subject.

Produces `campaign.updates`; serves `POST /api/v1/memory/similar` and the
read routes. A background sweep ages campaigns
`active -> dormant -> closed` and deletes patterns / fingerprints / long-closed
campaigns past `SM_MEMORY_RETENTION_DAYS` — the deletion lifecycle.
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
