"""`TemporalGraphState` — the graph as it stood at a point in time.

Fold an `EventTimeline` into an evolving node/edge set: each event contributes
nodes (its entities) and, via a caller-supplied `edge_fn`, edges. A node's
`first_seen` / `last_seen` widen as events for it arrive. `at(t)` returns the
subgraph of everything observed at or before `t`; `sample_at(t)` builds a
`GraphSample` from it so a graph model can score any historical moment.

Deterministic: the state is a pure fold of the (already ordered) timeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..graph.construct import GraphEdge, GraphNode, GraphSample, build_graph_sample
from .events import TemporalEvent
from .timeline import EventTimeline

__all__ = ["EdgeFn", "TemporalGraphState", "TemporalSnapshot"]

# Given an event, yield (src_entity, dst_entity, edge_type).
EdgeFn = Callable[[TemporalEvent], list[tuple[str, str, str]]]


def _default_entity_type(_entity: str) -> str:
    return "Host"


@dataclass(frozen=True)
class _NodeState:
    node_id: str
    node_type: str
    first_seen: float
    last_seen: float


@dataclass(frozen=True)
class _EdgeState:
    src_id: str
    dst_id: str
    edge_type: str
    first_seen: float
    last_seen: float
    count: int


@dataclass(frozen=True)
class TemporalSnapshot:
    at: float
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def to_sample(self, window_start: float | None = None) -> GraphSample:
        return build_graph_sample(
            self.nodes, self.edges,
            window_start=window_start if window_start is not None else (
                min((n.first_seen for n in self.nodes), default=self.at)
            ),
            window_end=self.at,
        )


@dataclass
class TemporalGraphState:
    edge_fn: EdgeFn
    entity_type_fn: Callable[[str], str] = _default_entity_type
    _events: list[tuple[float, TemporalEvent]] = field(default_factory=list, repr=False)

    @classmethod
    def from_timeline(
        cls, timeline: EventTimeline, *, edge_fn: EdgeFn,
        entity_type_fn: Callable[[str], str] | None = None,
    ) -> TemporalGraphState:
        state = cls(edge_fn=edge_fn, entity_type_fn=entity_type_fn or _default_entity_type)
        for event in timeline:
            state._events.append((timeline.effective_time(event), event))
        state._events.sort(key=lambda te: (te[0], te[1].event_id))
        return state

    def at(self, t: float) -> TemporalSnapshot:
        nodes: dict[str, _NodeState] = {}
        edges: dict[tuple[str, str, str], _EdgeState] = {}

        def _touch_node(entity: str, when: float) -> None:
            cur = nodes.get(entity)
            if cur is None:
                nodes[entity] = _NodeState(entity, self.entity_type_fn(entity), when, when)
            else:
                nodes[entity] = _NodeState(
                    cur.node_id, cur.node_type, min(cur.first_seen, when), max(cur.last_seen, when)
                )

        for when, event in self._events:
            if when > t:
                break
            for entity in event.entities:
                _touch_node(entity, when)
            for src, dst, etype in self.edge_fn(event):
                _touch_node(src, when)
                _touch_node(dst, when)
                k = (src, dst, etype)
                cur = edges.get(k)
                if cur is None:
                    edges[k] = _EdgeState(src, dst, etype, when, when, 1)
                else:
                    edges[k] = _EdgeState(
                        src, dst, etype, min(cur.first_seen, when), max(cur.last_seen, when),
                        cur.count + 1,
                    )

        return TemporalSnapshot(
            at=t,
            nodes=tuple(
                GraphNode(n.node_id, n.node_type, n.first_seen, n.last_seen)
                for n in sorted(nodes.values(), key=lambda n: n.node_id)
            ),
            edges=tuple(
                GraphEdge(e.src_id, e.dst_id, e.edge_type, e.last_seen)
                for e in sorted(edges.values(), key=lambda e: (e.src_id, e.dst_id, e.edge_type))
            ),
        )

    def latest(self) -> TemporalSnapshot:
        end = self._events[-1][0] if self._events else 0.0
        return self.at(end)
