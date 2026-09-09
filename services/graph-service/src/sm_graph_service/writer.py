"""Apply one `GraphCommandPayload` to Neo4j.

Rules (docs/architecture/data-model.md, ADR-007, PHASE 4):

- **Every Cypher statement is parameterized.** The only values ever interpolated
  into a query string are the node label and relationship type, and only after
  they pass the `sm_contracts` allowlist (`GRAPH_NODE_LABELS` / `GRAPH_REL_TYPES`)
  — Cypher cannot parameterize those. A label that is not on the list raises
  `PoisonError` and the record is dead-lettered.
- **Idempotent by `command_id`.** A command whose id is already in the
  `_GraphCommand` ledger is a no-op (`DUPLICATE`).
- **Out-of-order safe.** Each node / relationship carries a `_watermark`
  (the newest `observed_at` applied to it). A command older than the watermark
  updates `first_seen` / `last_seen` bounds but does not roll back properties
  (`STALE`).
- **Tenant invariants.** `tenant_id` is non-null on the payload (contract) and
  is written onto every node and relationship. Node keys are the synthetic
  per-tenant `uid` (`graph_node_uid`), so a relationship can only ever join two
  nodes of the command's own tenant — the "no cross-tenant edge" invariant holds
  by construction.
- **Missing endpoint nodes** for a `MERGE_EDGE` are created (thin) rather than
  failing.
- **Neo4j unavailable** surfaces as `GraphUnavailableError`; the engine turns it
  into a `TransientError` so the record is retried, not dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from sm_common.bus import PoisonError
from sm_common.graph import Graph
from sm_contracts import (
    GRAPH_NODE_KEY,
    GRAPH_NODE_LABELS,
    GRAPH_REL_TYPES,
    GraphCommandPayload,
    GraphEndpoint,
    GraphMutationOutcome,
    GraphOp,
    graph_node_uid,
    normalize_label,
)

__all__ = ["GraphWriter", "MutationResult"]

_log = structlog.get_logger("sm.graph_service.writer")

# Properties the writer owns; a command's `props` may never set these.
_RESERVED = frozenset(
    {"uid", "tenant_id", "graph", "first_seen", "last_seen", "observed_at", "_watermark"}
)


@dataclass(frozen=True)
class MutationResult:
    outcome: GraphMutationOutcome
    nodes_written: int
    relationships_written: int


def _safe_label(raw: str, allowed: frozenset[str], kind: str) -> str:
    label = normalize_label(raw)
    if label not in allowed:
        raise PoisonError(f"{kind} {label!r} is not on the graph allowlist")
    return label


def _clean_props(props: dict[str, object], key_prop: str) -> dict[str, object]:
    return {k: v for k, v in props.items() if k not in _RESERVED and k != key_prop}


class GraphWriter:
    def __init__(self, graph: Graph) -> None:
        self._graph = graph

    async def apply(self, cmd: GraphCommandPayload) -> MutationResult:
        if await self._already_applied(cmd.command_id):
            return MutationResult(GraphMutationOutcome.duplicate, 0, 0)

        if cmd.op in (GraphOp.merge_node, GraphOp.set_props):
            result = await self._apply_node(cmd)
        elif cmd.op is GraphOp.merge_edge:
            result = await self._apply_edge(cmd)
        else:  # PRUNE — the retention job, not built yet
            raise PoisonError(f"graph op {cmd.op.value} is not implemented")

        await self._record(cmd, result.outcome)
        return result

    # ---- idempotency ledger ------------------------------------------------
    async def _already_applied(self, command_id: object) -> bool:
        rows = await self._graph.run_read(
            "MATCH (c:_GraphCommand {command_id: $cid}) RETURN c.command_id AS id",
            {"cid": str(command_id)},
        )
        return bool(rows)

    async def _record(self, cmd: GraphCommandPayload, outcome: GraphMutationOutcome) -> None:
        await self._graph.run_write(
            "MERGE (c:_GraphCommand {command_id: $cid}) "
            "ON CREATE SET c.op = $op, c.outcome = $outcome, "
            "c.tenant_id = $tenant_id, c.applied_at = datetime()",
            {
                "cid": str(cmd.command_id),
                "op": cmd.op.value,
                "outcome": outcome.value,
                "tenant_id": str(cmd.tenant_id),
            },
        )

    # ---- node upsert -----------------------------------------------------
    async def _apply_node(self, cmd: GraphCommandPayload) -> MutationResult:
        label = _safe_label(cmd.label, GRAPH_NODE_LABELS, "node label")
        key_prop = GRAPH_NODE_KEY[label]
        if set(cmd.key) != {key_prop}:
            raise PoisonError(
                f"{label} command key must be exactly {{{key_prop!r}}}, got {sorted(cmd.key)}"
            )
        key_value = cmd.key[key_prop]
        params = {
            "uid": graph_node_uid(cmd.tenant_id, key_value),
            "tenant_id": str(cmd.tenant_id),
            "key_value": key_value,
            "observed_at": cmd.observed_at,
            "props": _clean_props(cmd.props, key_prop),
        }
        cypher = (
            f"MERGE (n:`{label}` {{uid: $uid}}) "
            f"  ON CREATE SET n.tenant_id = $tenant_id, n.`{key_prop}` = $key_value, "
            f"                n.graph = 'op', n.first_seen = $observed_at, "
            f"                n.last_seen = $observed_at, n._watermark = $observed_at, n += $props "
            f"  ON MATCH SET  n.first_seen = CASE WHEN $observed_at < n.first_seen "
            f"                               THEN $observed_at ELSE n.first_seen END, "
            f"                n.last_seen  = CASE WHEN $observed_at > n.last_seen "
            f"                               THEN $observed_at ELSE n.last_seen END "
            f"WITH n, ($observed_at >= n._watermark) AS current "
            f"FOREACH (_ IN CASE WHEN current THEN [1] ELSE [] END | "
            f"         SET n += $props, n._watermark = $observed_at) "
            f"RETURN current AS current"
        )
        rows = await self._graph.run_write(cypher, params)
        current = bool(rows and rows[0]["current"])
        if current:
            return MutationResult(GraphMutationOutcome.applied, 1, 0)
        return MutationResult(GraphMutationOutcome.stale, 0, 0)

    # ---- edge upsert ---------------------------------------------------
    async def _apply_edge(self, cmd: GraphCommandPayload) -> MutationResult:
        if cmd.start is None or cmd.end is None:
            raise PoisonError("MERGE_EDGE command is missing start / end")
        rel = _safe_label(cmd.label, GRAPH_REL_TYPES, "relationship type")
        start_label, start_prop, start_val = _endpoint(cmd.start)
        end_label, end_prop, end_val = _endpoint(cmd.end)
        params = {
            "start_uid": graph_node_uid(cmd.tenant_id, start_val),
            "end_uid": graph_node_uid(cmd.tenant_id, end_val),
            "tenant_id": str(cmd.tenant_id),
            "start_val": start_val,
            "end_val": end_val,
            "observed_at": cmd.observed_at,
            "props": _clean_props(cmd.props, ""),
        }
        cypher = (
            f"MERGE (s:`{start_label}` {{uid: $start_uid}}) "
            f"  ON CREATE SET s.tenant_id = $tenant_id, s.`{start_prop}` = $start_val, "
            f"                s.graph = 'op', s.first_seen = $observed_at, "
            f"                s.last_seen = $observed_at, s._watermark = $observed_at "
            f"  ON MATCH SET  s.last_seen = CASE WHEN $observed_at > s.last_seen "
            f"                               THEN $observed_at ELSE s.last_seen END "
            f"MERGE (e:`{end_label}` {{uid: $end_uid}}) "
            f"  ON CREATE SET e.tenant_id = $tenant_id, e.`{end_prop}` = $end_val, "
            f"                e.graph = 'op', e.first_seen = $observed_at, "
            f"                e.last_seen = $observed_at, e._watermark = $observed_at "
            f"  ON MATCH SET  e.last_seen = CASE WHEN $observed_at > e.last_seen "
            f"                               THEN $observed_at ELSE e.last_seen END "
            f"MERGE (s)-[r:`{rel}`]->(e) "
            f"  ON CREATE SET r.tenant_id = $tenant_id, r.graph = 'op', "
            f"                r.observed_at = $observed_at, r.first_seen = $observed_at, "
            f"                r.last_seen = $observed_at, r += $props "
            f"WITH r, ($observed_at >= r.observed_at) AS current "
            f"FOREACH (_ IN CASE WHEN current THEN [1] ELSE [] END | "
            f"         SET r += $props, r.observed_at = $observed_at, "
            f"             r.last_seen = CASE WHEN $observed_at > r.last_seen "
            f"                            THEN $observed_at ELSE r.last_seen END) "
            f"RETURN current AS current"
        )
        rows = await self._graph.run_write(cypher, params)
        current = bool(rows and rows[0]["current"])
        if current:
            return MutationResult(GraphMutationOutcome.applied, 2, 1)
        return MutationResult(GraphMutationOutcome.stale, 0, 0)


def _endpoint(ep: GraphEndpoint) -> tuple[str, str, object]:
    label = _safe_label(ep.label, GRAPH_NODE_LABELS, "endpoint label")
    key_prop = GRAPH_NODE_KEY[label]
    if set(ep.key) != {key_prop}:
        raise PoisonError(
            f"{label} endpoint key must be exactly {{{key_prop!r}}}, got {sorted(ep.key)}"
        )
    return label, key_prop, ep.key[key_prop]
