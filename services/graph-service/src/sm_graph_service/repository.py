"""Read-only, tenant-scoped, bounded graph queries (ADR-007, CONTRACTS.md §5).

Every query here:

- is **parameterized** — the only things interpolated are a node label (checked
  against `sm_contracts.GRAPH_NODE_LABELS`) and an integer traversal depth
  (clamped to `[1, SM_NEO4J_TRAVERSAL_MAX_DEPTH]`). Cypher can parameterize
  neither. No caller value ever reaches the query text.
- is **tenant-scoped** — the tenant comes from the verified internal principal,
  not a request field. Every node on every traversal path must carry the same
  `tenant_id`.
- is **row-capped** (`SM_NEO4J_QUERY_MAX_ROWS`) and **time-limited** (the driver
  carries `SM_NEO4J_QUERY_TIMEOUT_MS`).

Internal `_`-prefixed properties (`_watermark`) and the synthetic `uid` are
stripped from every response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sm_common.errors import ValidationFailed
from sm_common.graph import Graph
from sm_contracts import GRAPH_NODE_KEY, GRAPH_NODE_LABELS, normalize_label

__all__ = ["GraphEdgeView", "GraphNodeView", "GraphRepository", "GraphView", "PathView"]

_HIDDEN_PROP_PREFIX = "_"
_HIDDEN_PROPS = frozenset({"uid"})


def _public(props: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in props.items()
        if not k.startswith(_HIDDEN_PROP_PREFIX) and k not in _HIDDEN_PROPS
    }


def _label(raw: str) -> tuple[str, str]:
    label = normalize_label(raw)
    if label not in GRAPH_NODE_LABELS:
        raise ValidationFailed(f"unknown node label {label!r}")
    return label, GRAPH_NODE_KEY[label]


@dataclass(frozen=True)
class GraphNodeView:
    id: str
    labels: list[str]
    properties: dict[str, Any]


@dataclass(frozen=True)
class GraphEdgeView:
    src: str
    dst: str
    type: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class GraphView:
    nodes: list[GraphNodeView]
    edges: list[GraphEdgeView]
    truncated: bool


@dataclass(frozen=True)
class PathView:
    found: bool
    length: int | None
    nodes: list[GraphNodeView]
    edges: list[GraphEdgeView]


class GraphRepository:
    def __init__(self, graph: Graph, *, max_rows: int, max_depth: int) -> None:
        self._graph = graph
        self._max_rows = max_rows
        self._max_depth = max_depth

    def _clamp_depth(self, depth: int) -> int:
        return max(1, min(int(depth), self._max_depth))

    def _clamp_limit(self, limit: int | None) -> int:
        if limit is None:
            return self._max_rows
        return max(1, min(int(limit), self._max_rows))

    # ---- point lookup ---------------------------------------------------
    async def entity(self, tenant_id: UUID, label: str, key: str) -> GraphNodeView | None:
        lbl, key_prop = _label(label)
        rows = await self._graph.run_read(
            f"MATCH (n:`{lbl}` {{tenant_id: $tenant}}) WHERE n.`{key_prop}` = $key "
            f"RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props LIMIT 1",
            {"tenant": str(tenant_id), "key": key},
        )
        if not rows:
            return None
        r = rows[0]
        return GraphNodeView(id=r["id"], labels=list(r["labels"]), properties=_public(r["props"]))

    # ---- bounded neighbourhood ---------------------------------------
    async def neighbors(
        self, tenant_id: UUID, label: str, key: str, *, depth: int = 1, limit: int | None = None
    ) -> GraphView:
        lbl, key_prop = _label(label)
        d = self._clamp_depth(depth)
        row_cap = self._clamp_limit(limit)
        params = {"tenant": str(tenant_id), "key": key, "cap": row_cap}

        node_rows = await self._graph.run_read(
            f"MATCH (a:`{lbl}` {{tenant_id: $tenant}}) WHERE a.`{key_prop}` = $key "
            f"OPTIONAL MATCH p = (a)-[*1..{d}]-(b) "
            f"WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant) "
            f"WITH a, [x IN collect(DISTINCT b) WHERE x IS NOT NULL] AS others "
            f"UNWIND ([a] + others) AS node "
            f"WITH DISTINCT node LIMIT $cap "
            f"RETURN elementId(node) AS id, labels(node) AS labels, properties(node) AS props",
            params,
        )
        edge_rows = await self._graph.run_read(
            f"MATCH (a:`{lbl}` {{tenant_id: $tenant}}) WHERE a.`{key_prop}` = $key "
            f"MATCH p = (a)-[*1..{d}]-(b) "
            f"WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant) "
            f"UNWIND relationships(p) AS r "
            f"WITH DISTINCT r LIMIT $cap "
            f"RETURN elementId(startNode(r)) AS src, elementId(endNode(r)) AS dst, "
            f"       type(r) AS type, properties(r) AS props",
            params,
        )
        nodes = [
            GraphNodeView(id=r["id"], labels=list(r["labels"]), properties=_public(r["props"]))
            for r in node_rows
        ]
        edges = [
            GraphEdgeView(src=r["src"], dst=r["dst"], type=r["type"], properties=_public(r["props"]))
            for r in edge_rows
        ]
        truncated = len(node_rows) >= row_cap or len(edge_rows) >= row_cap
        return GraphView(nodes=nodes, edges=edges, truncated=truncated)

    # ---- shortest attack path -------------------------------------
    async def attack_path(
        self,
        tenant_id: UUID,
        src: tuple[str, str],
        dst: tuple[str, str],
        *,
        max_depth: int = 4,
    ) -> PathView:
        src_label, src_key_prop = _label(src[0])
        dst_label, dst_key_prop = _label(dst[0])
        d = self._clamp_depth(max_depth)
        rows = await self._graph.run_read(
            f"MATCH (a:`{src_label}` {{tenant_id: $tenant}}) WHERE a.`{src_key_prop}` = $src "
            f"MATCH (b:`{dst_label}` {{tenant_id: $tenant}}) WHERE b.`{dst_key_prop}` = $dst "
            f"MATCH p = shortestPath((a)-[*..{d}]-(b)) "
            f"WHERE all(x IN nodes(p) WHERE x.tenant_id = $tenant) "
            f"RETURN [n IN nodes(p) | {{id: elementId(n), labels: labels(n), props: properties(n)}}] AS ns, "
            f"       [r IN relationships(p) | {{src: elementId(startNode(r)), dst: elementId(endNode(r)), "
            f"                                  type: type(r), props: properties(r)}}] AS rs, "
            f"       length(p) AS len LIMIT 1",
            {"tenant": str(tenant_id), "src": src[1], "dst": dst[1]},
        )
        if not rows:
            return PathView(found=False, length=None, nodes=[], edges=[])
        r = rows[0]
        nodes = [
            GraphNodeView(id=n["id"], labels=list(n["labels"]), properties=_public(n["props"]))
            for n in r["ns"]
        ]
        edges = [
            GraphEdgeView(src=e["src"], dst=e["dst"], type=e["type"], properties=_public(e["props"]))
            for e in r["rs"]
        ]
        return PathView(found=True, length=int(r["len"]), nodes=nodes, edges=edges)
