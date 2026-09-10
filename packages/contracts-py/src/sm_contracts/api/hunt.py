"""Threat-hunting contracts (Phase 11).

The security rule: **raw LLM output never becomes executed Cypher.** The pipeline
is `natural language -> intent -> QueryPlan -> validation -> authorization ->
parameterized Cypher -> result -> explanation`. `QueryPlan` is a **closed
schema** — the LLM (or a structured form) produces one of a fixed set of intents
over typed entity selectors; `graph-service` validates it, scopes it to the
caller's tenant, and compiles it to one of a fixed set of parameterized Cypher
templates. Anything outside the capability set is `unsupported_query`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc

__all__ = [
    "EntitySelector",
    "HuntEntityType",
    "HuntExplainRequest",
    "HuntIntent",
    "HuntResult",
    "NlHuntRequest",
    "PlanResponse",
    "QueryLimits",
    "QueryPlan",
    "SocHuntRequest",
    "SocHuntResponse",
]

HuntIntent = Literal[
    "find_entity",          # locate a node by type + natural key
    "list_related",         # neighbours of an entity (optionally filtered by relationship type)
    "path_between",         # shortest path between two entities
    "detections_for",       # detections involving an entity
    "chains_for",           # attack chains involving an entity
    "indicator_sightings",  # hosts/identities/processes an IOC (ip / domain / file) touches
    "technique_usage",      # subjects mapped to an ATT&CK technique
]

HuntEntityType = Literal[
    "identity",
    "host",
    "ip",
    "domain",
    "process",
    "file",
    "detection",
    "attack_chain",
    "attack_technique",
    "threat_actor",
    "campaign",
]


class EntitySelector(SmBaseModel):
    type: HuntEntityType
    #: The entity's natural key value. Always bound as a Cypher parameter — it
    #: never reaches the query text.
    value: str = Field(min_length=1, max_length=512)


class HuntTimeRange(SmBaseModel):
    start: datetime | None = None
    end: datetime | None = None

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return to_utc(v) if v is not None else None


class QueryLimits(SmBaseModel):
    max_depth: int = Field(default=2, ge=1, le=4)
    max_rows: int = Field(default=100, ge=1, le=500)


class QueryPlan(SmBaseModel):
    """A validated, capability-bounded hunt request. Deterministically compiled
    to a parameterized Cypher template by `graph-service` — never executed as
    free text."""

    intent: HuntIntent
    #: 1 selector for most intents; exactly 2 for `path_between`.
    selectors: list[EntitySelector] = Field(min_length=1, max_length=2)
    #: Optional relationship-type filter for `list_related`. Each is checked
    #: against `GRAPH_REL_TYPES` server-side; an unknown type is rejected.
    rel_types: list[str] = Field(default_factory=list, max_length=8)
    time_range: HuntTimeRange | None = None
    limits: QueryLimits = Field(default_factory=QueryLimits)


class NlHuntRequest(SmBaseModel):
    """A natural-language hunt. `api-gateway` sends this to `ai-analyst`, which
    returns a `QueryPlan` or `unsupported`."""

    query: str = Field(min_length=1, max_length=1_000)
    max_rows: int = Field(default=100, ge=1, le=500)


class PlanResponse(SmBaseModel):
    """`ai-analyst`'s answer to an `NlHuntRequest`."""

    supported: bool
    plan: QueryPlan | None = None
    #: Set when `supported` is False — why the request could not be planned
    #: (malformed, out of scope, could not parse the model's output, no LLM).
    unsupported_reason: str = Field(default="", max_length=300)


class HuntResult(SmBaseModel):
    intent: HuntIntent
    plan: QueryPlan
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    row_count: int = Field(ge=0)
    truncated: bool = False
    #: sha256 of the compiled Cypher **template** (not the parameters) — proves
    #: the query was one of the fixed set; leaks no data.
    cypher_fingerprint: str = Field(default="", max_length=64)
    #: Grounded, cites the plan. Filled by `ai-analyst`; empty from `graph-service`.
    explanation: str = Field(default="", max_length=4_000)


class HuntExplainRequest(SmBaseModel):
    """`api-gateway` -> `ai-analyst`: turn a `HuntResult` (no explanation) into
    one with a grounded natural-language summary."""

    result: HuntResult


class SocHuntRequest(SmBaseModel):
    """The browser-facing hunt. Exactly one of `query` (natural language, planned
    by `ai-analyst`) or `plan` (a structured plan built by the UI, no LLM)."""

    query: str | None = Field(default=None, min_length=1, max_length=1_000)
    plan: QueryPlan | None = None
    max_rows: int = Field(default=100, ge=1, le=500)


class SocHuntResponse(SmBaseModel):
    supported: bool
    unsupported_reason: str = Field(default="", max_length=300)
    result: HuntResult | None = None
    #: The `hunt_query` history row id, when one was recorded.
    history_id: str | None = None
