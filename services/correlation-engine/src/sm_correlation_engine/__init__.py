"""SentinelMesh correlation engine (req 6).

Turns the `detections` stream into multi-stage **attack chains**: each detection
is placed on an ATT&CK-derived kill-chain stage (`sm_contracts.stage_for_technique`
— an unknown technique lands on `AttackStage.unknown`, never a guess), grouped by
subject inside a fixed tumbling window into a deterministic-id chain, and the
chain's `progression`, probabilistic `confidence` (capped below 1.0 — never a
certainty), `status` and a versioned deterministic `score` (`CHAIN_SCORE_VERSION`)
are recomputed. Out-of-order and duplicate detections are handled by set-valued
stage membership and `min`/`max` timestamps.

Consumes `detections` (group `correlation`); writes `attack_chain` /
`attack_chain_stage`; produces `attack_chains`; serves
`GET /api/v1/chains[/{chain_id}]`.
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
