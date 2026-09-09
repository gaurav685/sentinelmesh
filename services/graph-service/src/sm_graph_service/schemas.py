"""Response models for the internal graph-query API (DRAFT — Phase 4 Unit 3).

Kept in the service (not `sm_contracts`) until the read surface settles.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .intel import GraphIntel
from .repository import GraphEdgeView, GraphNodeView, GraphView, PathView

__all__ = [
    "EntityResponse",
    "GraphIntelResponse",
    "GraphNodeModel",
    "NeighborsResponse",
    "PathResponse",
]


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


class _NodeAnomaly(BaseModel):
    node_id: str
    node_type: str
    normalized_score: float = Field(ge=0.0, le=1.0)
    contributing_features: list[str]


class _Cluster(BaseModel):
    cluster_id: int
    size: int
    cohesion: float
    node_types: list[str]


class GraphIntelResponse(BaseModel):
    """Structural graph-intelligence over a bounded neighbourhood (Phase 8).

    Deterministic, standard-library. `anomalies` lists only nodes that crossed
    the threshold; `subgraph_score` is a likelihood in [0, 1], never a certainty.
    """

    subject_label: str
    subject_key: str
    feature_schema_version: str
    node_count: int
    edge_count: int
    truncated: bool = Field(description="True if the neighbourhood read hit the row cap.")
    anomalies: list[_NodeAnomaly]
    clusters: list[_Cluster]
    subgraph_suspicious: bool
    subgraph_score: float = Field(ge=0.0, le=1.0)
    subgraph_rationale: str
    methods: dict[str, str]

    @classmethod
    def of(cls, intel: GraphIntel) -> GraphIntelResponse:
        return cls(
            subject_label=intel.subject_label, subject_key=intel.subject_key,
            feature_schema_version=intel.feature_schema_version,
            node_count=intel.node_count, edge_count=intel.edge_count, truncated=intel.truncated,
            anomalies=[
                _NodeAnomaly(
                    node_id=a.node_id, node_type=a.node_type,
                    normalized_score=a.normalized_score,
                    contributing_features=a.contributing_features,
                )
                for a in intel.anomalies
            ],
            clusters=[
                _Cluster(cluster_id=c.cluster_id, size=c.size, cohesion=c.cohesion,
                         node_types=c.node_types)
                for c in intel.clusters
            ],
            subgraph_suspicious=intel.subgraph_suspicious, subgraph_score=intel.subgraph_score,
            subgraph_rationale=intel.subgraph_rationale, methods=intel.methods,
        )
