"""Deterministic hunt-plan validation, compilation and execution.

`raw LLM output -> executed Cypher` is impossible here: `graph-service` only ever
receives a validated `QueryPlan` (a closed schema of a fixed intent set over
typed entity selectors), and each intent maps to **one constant, parameterized
Cypher template**. The only things ever interpolated into a template are:

- a node label, checked against `sm_contracts.GRAPH_NODE_LABELS`;
- relationship-type names, each checked against `sm_contracts.GRAPH_REL_TYPES`;
- an integer traversal depth, clamped to `[1, SM_NEO4J_TRAVERSAL_MAX_DEPTH]`.

Every entity value the caller supplied is a `$`-parameter — it never reaches the
query text. Every query is scoped to `$tenant` (from the verified internal
token), read-only, and row-capped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sm_common.errors import ValidationFailed
from sm_common.graph import Graph
from sm_contracts import GRAPH_NODE_KEY, GRAPH_REL_TYPES, HuntResult, QueryPlan
from sm_contracts.api.hunt import HuntIntent

__all__ = ["HuntRunner", "compile_plan", "validate_plan"]

# entity-selector type -> graph node label
_ENTITY_LABEL: dict[str, str] = {
    "identity": "Identity",
    "host": "Host",
    "ip": "IpAddress",
    "domain": "Domain",
    "process": "Process",
    "file": "File",
    "detection": "Detection",
    "attack_chain": "AttackChain",
    "attack_technique": "AttackTechnique",
    "threat_actor": "ThreatActor",
    "campaign": "Campaign",
}

# which selector types each intent accepts, and how many selectors
_INTENT_SELECTORS: dict[HuntIntent, tuple[int, frozenset[str]]] = {
    "find_entity": (1, frozenset(_ENTITY_LABEL)),
    "list_related": (1, frozenset(_ENTITY_LABEL)),
    "path_between": (2, frozenset(_ENTITY_LABEL)),
    "detections_for": (1, frozenset({"identity", "host", "ip", "process", "file"})),
    "chains_for": (1, frozenset({"identity", "host", "ip", "process"})),
    "indicator_sightings": (1, frozenset({"ip", "domain", "file"})),
    "technique_usage": (1, frozenset({"attack_technique"})),
}


@dataclass(frozen=True)
class CompiledHunt:
    cypher: str
    params: dict[str, object]
    #: sha256 of `cypher` (the template text — parameters are separate, so this
    #: leaks nothing and proves the query was one of the fixed set).
    fingerprint: str


def validate_plan(plan: QueryPlan) -> None:
    """Raise `ValidationFailed` for anything outside the capability set."""
    spec = _INTENT_SELECTORS.get(plan.intent)
    if spec is None:  # pragma: no cover - Literal makes this unreachable
        raise ValidationFailed(f"unsupported intent {plan.intent!r}")
    want_count, allowed_types = spec
    if len(plan.selectors) != want_count:
        raise ValidationFailed(
            f"intent {plan.intent!r} needs exactly {want_count} selector(s), got {len(plan.selectors)}"
        )
    for sel in plan.selectors:
        if sel.type not in allowed_types:
            raise ValidationFailed(
                f"selector type {sel.type!r} is not valid for intent {plan.intent!r}"
            )
    for rt in plan.rel_types:
        if rt not in GRAPH_REL_TYPES:
            raise ValidationFailed(f"unknown relationship type {rt!r}")
    if plan.rel_types and plan.intent != "list_related":
        raise ValidationFailed("rel_types is only valid for the 'list_related' intent")


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


def compile_plan(
    plan: QueryPlan, tenant_id: UUID, *, max_rows: int, max_depth: int
) -> CompiledHunt:
    """Compile a **validated** plan to one parameterized Cypher template."""
    validate_plan(plan)
    depth = _clamp(plan.limits.max_depth, 1, max_depth)
    cap = _clamp(plan.limits.max_rows, 1, max_rows)
    params: dict[str, object] = {"tenant": str(tenant_id), "cap": cap}

    def label_key(idx: int) -> tuple[str, str]:
        sel = plan.selectors[idx]
        label = _ENTITY_LABEL[sel.type]
        params[f"v{idx}"] = sel.value
        return label, GRAPH_NODE_KEY[label]

    if plan.intent == "find_entity":
        lbl, key = label_key(0)
        cypher = (
            f"MATCH (n:`{lbl}` {{tenant_id: $tenant}}) WHERE n.`{key}` = $v0 "
            f"RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props LIMIT $cap"
        )
    elif plan.intent == "list_related":
        lbl, key = label_key(0)
        rel = ""
        if plan.rel_types:
            rel = ":" + "|".join(sorted(set(plan.rel_types)))
        cypher = (
            f"MATCH (a:`{lbl}` {{tenant_id: $tenant}}) WHERE a.`{key}` = $v0 "
            f"MATCH p = (a)-[{rel}*1..{depth}]-(b) "
            f"WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant) "
            f"WITH DISTINCT b LIMIT $cap "
            f"RETURN elementId(b) AS id, labels(b) AS labels, properties(b) AS props"
        )
    elif plan.intent == "path_between":
        la, ka = label_key(0)
        lb, kb = label_key(1)
        cypher = (
            f"MATCH (a:`{la}` {{tenant_id: $tenant}}) WHERE a.`{ka}` = $v0 "
            f"MATCH (b:`{lb}` {{tenant_id: $tenant}}) WHERE b.`{kb}` = $v1 "
            f"MATCH p = shortestPath((a)-[*..{depth}]-(b)) "
            f"WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant) "
            f"RETURN [n IN nodes(p) | {{id: elementId(n), labels: labels(n), "
            f"props: properties(n)}}] AS path_nodes, length(p) AS length LIMIT 1"
        )
    elif plan.intent in ("detections_for", "chains_for"):
        lbl, key = label_key(0)
        target = "Detection" if plan.intent == "detections_for" else "AttackChain"
        cypher = (
            f"MATCH (a:`{lbl}` {{tenant_id: $tenant}}) WHERE a.`{key}` = $v0 "
            f"MATCH p = (a)-[*1..{depth}]-(t:`{target}`) "
            f"WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant) "
            f"WITH DISTINCT t LIMIT $cap "
            f"RETURN elementId(t) AS id, labels(t) AS labels, properties(t) AS props"
        )
    elif plan.intent == "indicator_sightings":
        lbl, key = label_key(0)
        cypher = (
            f"MATCH (ind:`{lbl}` {{tenant_id: $tenant}}) WHERE ind.`{key}` = $v0 "
            f"MATCH p = (ind)-[*1..{depth}]-(sub) "
            f"WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant) "
            f"  AND any(l IN labels(sub) WHERE l IN ['Host', 'Identity', 'Process']) "
            f"WITH DISTINCT sub LIMIT $cap "
            f"RETURN elementId(sub) AS id, labels(sub) AS labels, properties(sub) AS props"
        )
    else:  # technique_usage
        label_key(0)  # binds $v0
        cypher = (
            "MATCH (t:`AttackTechnique` {tenant_id: $tenant}) WHERE t.`technique_id` = $v0 "
            "MATCH (sub)-[:MAPPED_TO]->(t) WHERE sub.tenant_id = $tenant "
            "WITH DISTINCT sub LIMIT $cap "
            "RETURN elementId(sub) AS id, labels(sub) AS labels, properties(sub) AS props"
        )

    return CompiledHunt(
        cypher=cypher,
        params=params,
        fingerprint=hashlib.sha256(cypher.encode()).hexdigest(),
    )


_HIDDEN_PREFIX = "_"
_HIDDEN = frozenset({"uid"})


def _public(props: dict[str, object]) -> dict[str, object]:
    return {
        k: v for k, v in props.items() if not k.startswith(_HIDDEN_PREFIX) and k not in _HIDDEN
    }


class HuntRunner:
    def __init__(self, graph: Graph, *, max_rows: int, max_depth: int) -> None:
        self._graph = graph
        self._max_rows = max_rows
        self._max_depth = max_depth

    async def run(self, plan: QueryPlan, tenant_id: UUID) -> HuntResult:
        compiled = compile_plan(
            plan, tenant_id, max_rows=self._max_rows, max_depth=self._max_depth
        )
        raw = await self._graph.run_read(compiled.cypher, compiled.params)

        rows: list[dict[str, object]] = []
        if plan.intent == "path_between":
            for r in raw:
                nodes = [
                    {"id": n["id"], "labels": list(n["labels"]), "properties": _public(n["props"])}
                    for n in r.get("path_nodes", [])
                ]
                rows.append({"kind": "path", "length": r.get("length"), "nodes": nodes})
        else:
            for r in raw:
                rows.append(
                    {
                        "id": r["id"],
                        "labels": list(r["labels"]),
                        "properties": _public(r["props"]),
                    }
                )

        cap = compiled.params["cap"]
        truncated = isinstance(cap, int) and len(rows) >= cap and plan.intent != "path_between"
        return HuntResult(
            intent=plan.intent,
            plan=plan,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            cypher_fingerprint=compiled.fingerprint,
        )
