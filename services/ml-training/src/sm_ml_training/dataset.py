"""Datasets for the graph-model pipeline.

A `GraphDataset` is a set of labelled graph samples: for each sample, the
`GraphSample` itself plus a per-node label (`1` = anomalous / of interest,
`0` = benign). The always-available structural detector is unsupervised, so the
labels are used **only** for validation and evaluation, never for fitting weights.

`synthetic_fixture_dataset(seed)` builds a small, deterministic, clearly-labelled
toy dataset — a plumbing check, **not a benchmark**. A real benchmark is loaded
from `dataset_path` and carries an id + sha256 (ADR-024 — no dataset ships).
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from sm_ml.graph import GraphEdge, GraphNode, GraphSample, build_graph_sample

__all__ = ["GraphDataset", "LabelledSample", "load_dataset", "synthetic_fixture_dataset"]


@dataclass(frozen=True)
class LabelledSample:
    sample: GraphSample
    node_labels: dict[str, int]  # node_id -> 0 (benign) | 1 (anomalous)

    def __post_init__(self) -> None:
        missing = set(self.sample.node_ids) - set(self.node_labels)
        if missing:
            raise ValueError(f"unlabelled node(s): {sorted(missing)}")


@dataclass(frozen=True)
class GraphDataset:
    dataset_id: str
    dataset_kind: str
    sha256: str
    samples: tuple[LabelledSample, ...]

    @property
    def num_samples(self) -> int:
        return len(self.samples)

    @property
    def num_anomalous_nodes(self) -> int:
        return sum(v for s in self.samples for v in s.node_labels.values())


def synthetic_fixture_dataset(seed: int, *, n_samples: int = 6) -> GraphDataset:
    rng = random.Random(seed)  # noqa: S311 - deterministic fixture generator, not crypto
    samples: list[LabelledSample] = []
    for si in range(n_samples):
        n_benign = 8 + rng.randint(0, 4)
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        labels: dict[str, int] = {}

        # a benign ring of hosts
        for i in range(n_benign):
            nid = f"s{si}_h{i}"
            nodes.append(GraphNode(nid, "Host", first_seen=float(i), last_seen=float(i + 5)))
            labels[nid] = 0
        for i in range(n_benign):
            edges.append(GraphEdge(
                f"s{si}_h{i}", f"s{si}_h{(i + 1) % n_benign}", "CONNECTED_TO", float(i),
            ))

        # one injected anomalous hub that fans out to every host
        hub = f"s{si}_evil"
        nodes.append(GraphNode(hub, "IpAddress", first_seen=0.0, last_seen=float(n_benign + 10)))
        labels[hub] = 1
        for i in range(n_benign):
            edges.append(GraphEdge(hub, f"s{si}_h{i}", "CONNECTED_TO", float(i)))

        samples.append(LabelledSample(build_graph_sample(nodes, edges), labels))

    blob = _canonical_bytes(samples)
    return GraphDataset(
        dataset_id=f"synthetic-fixture-seed{seed}-n{n_samples}",
        dataset_kind="synthetic_fixture",
        sha256=hashlib.sha256(blob).hexdigest(),
        samples=tuple(samples),
    )


def load_dataset(path: str, *, dataset_id: str | None = None) -> GraphDataset:
    """Load a real benchmark dataset. The file format is JSON lines, one graph
    per line: `{"nodes": [...], "edges": [...], "labels": {...}}`. No dataset
    ships in this repository (ADR-024)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    raw = p.read_bytes()
    samples: list[LabelledSample] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        nodes = [
            GraphNode(n["node_id"], n["node_type"], float(n["first_seen"]), float(n["last_seen"]))
            for n in doc["nodes"]
        ]
        edges = [
            GraphEdge(e["src_id"], e["dst_id"], e["edge_type"], float(e["observed_at"]))
            for e in doc["edges"]
        ]
        labels = {k: int(v) for k, v in doc["labels"].items()}
        samples.append(LabelledSample(build_graph_sample(nodes, edges), labels))
    return GraphDataset(
        dataset_id=dataset_id or p.stem,
        dataset_kind="benchmark",
        sha256=hashlib.sha256(raw).hexdigest(),
        samples=tuple(samples),
    )


def _canonical_bytes(samples: list[LabelledSample]) -> bytes:
    payload = [
        {
            "node_ids": list(s.sample.node_ids),
            "node_features": [list(r) for r in s.sample.node_features],
            "edge_index": [list(p) for p in s.sample.edge_index],
            "labels": s.node_labels,
        }
        for s in samples
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
