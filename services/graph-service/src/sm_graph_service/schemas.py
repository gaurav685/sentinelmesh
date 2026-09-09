"""Response models for the internal graph-query API (DRAFT — Phase 4 Unit 3).

Kept in the service (not `sm_contracts`) until the read surface settles.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .repository import GraphEdgeView, GraphNodeView, GraphView, PathView

__all__ = ["EntityResponse", "GraphNodeModel", "NeighborsResponse", "PathResponse"]


class GraphNodeModel(BaseModel):
    id: str
    labels: list[str]
    properties: dict[str, Any]

    @classmethod
    def of(cls, v: GraphNodeView) -> GraphNodeModel:
        return cls(id=v.id, labels=v.labels, properties=v.properties)


class GraphEdgeModel(BaseModel):
    src: str
    dst: str
    type: str
    properties: dict[str, Any]

    @classmethod
    def of(cls, v: GraphEdgeView) -> GraphEdgeModel:
        return cls(src=v.src, dst=v.dst, type=v.type, properties=v.properties)


class EntityResponse(BaseModel):
    entity: GraphNodeModel


class NeighborsResponse(BaseModel):
    depth: int
    nodes: list[GraphNodeModel]
    edges: list[GraphEdgeModel]
    truncated: bool = Field(description="True if the row cap was hit; the view is partial.")

    @classmethod
    def of(cls, depth: int, v: GraphView) -> NeighborsResponse:
        return cls(
            depth=depth,
            nodes=[GraphNodeModel.of(n) for n in v.nodes],
            edges=[GraphEdgeModel.of(e) for e in v.edges],
            truncated=v.truncated,
        )


class PathResponse(BaseModel):
    found: bool
    length: int | None
    nodes: list[GraphNodeModel]
    edges: list[GraphEdgeModel]

    @classmethod
    def of(cls, v: PathView) -> PathResponse:
        return cls(
            found=v.found,
            length=v.length,
            nodes=[GraphNodeModel.of(n) for n in v.nodes],
            edges=[GraphEdgeModel.of(e) for e in v.edges],
        )
