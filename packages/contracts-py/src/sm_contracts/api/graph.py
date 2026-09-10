"""Graph read-API contracts (Phase 9).

`graph-service` owns the write path and the Cypher; its query endpoints return
these shapes and `api-gateway` proxies them to the browser unchanged. The SOC
dashboard's attack-graph view consumes the generated TypeScript for these models
— it never re-declares a node/edge shape.

`properties` is whatever the graph node/edge carries. It is display-only in the
UI and is never used for an authorization or routing decision.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..common import SmBaseModel

__all__ = [
    "GraphEdge",
    "GraphNeighborhood",
    "GraphNode",
    "GraphPath",
]


class GraphNode(SmBaseModel):
    id: str = Field(min_length=1, max_length=256)
    labels: list[str] = Field(default_factory=list, max_length=32)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(SmBaseModel):
    src: str = Field(min_length=1, max_length=256)
    dst: str = Field(min_length=1, max_length=256)
    type: str = Field(min_length=1, max_length=128)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphNeighborhood(SmBaseModel):
    """A bounded, tenant-scoped neighbourhood around one root node.

    `truncated` is true when the server row cap was hit — the view is partial and
    the UI must say so rather than implying the entity has no other neighbours.
    """

    root_id: str = Field(min_length=1, max_length=256)
    depth: int = Field(ge=1, le=8)
    nodes: list[GraphNode] = Field(default_factory=list, max_length=5000)
    edges: list[GraphEdge] = Field(default_factory=list, max_length=20000)
    truncated: bool = False


class GraphPath(SmBaseModel):
    """The shortest path between two nodes, or `found=False` when there is none."""

    found: bool
    length: int | None = Field(default=None, ge=0)
    nodes: list[GraphNode] = Field(default_factory=list, max_length=64)
    edges: list[GraphEdge] = Field(default_factory=list, max_length=64)
