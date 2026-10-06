#!/usr/bin/env python3
"""Build a real graph-structured derivative of NSL-KDD for GNN training (remediation item 14/15).

    python scripts/build_graph_dataset_nsl_kdd.py \
        --file C:\\Sentinel_Mesh\\archive\\KDDTrain+.txt \
        --out ml/datasets/nsl-kdd-graph/train.jsonl \
        --window-size 500

CICIDS2017 and UNSW-NB15 were investigated for this (remediation item 11/12)
and are BLOCKED: both now require a manual registration/access step at the
source that cannot be scripted from this environment (see
`docs/PRIORITY_REMEDIATION_PLAN.md`). The repository owner confirmed NSL-KDD
should be used instead -- it is the platform's existing real, local, labeled
dataset, already used as the Isolation Forest / statistical baseline.

NSL-KDD carries no real IP addresses or graph structure of its own (a known
property of the dataset). This script builds a REAL, deterministic graph
from REAL NSL-KDD rows using the exact same honest placeholder-IP convention
`scripts/ingest_nsl_kdd.py` already uses for the live ingestion pipeline (so
a graph built here is structurally consistent with what the real pipeline
would build from the same rows):

  - each row becomes one `IpAddress` source node, with a synthesized id
    `10.50.<row//256>.<row%256>` -- identical scheme to `ingest_nsl_kdd.py`
  - each row's destination is one of 16 fixed `IpAddress` hub nodes
    (`10.60.0.1`..`10.60.0.16`), the same fixed pool `ingest_nsl_kdd.py` uses
  - a `CONNECTED_TO` edge from source to destination, timestamped by the
    row's position in the file (deterministic, not wall-clock)
  - the source node's label is the row's REAL NSL-KDD ground truth
    (0 = normal, 1 = any attack type) -- never fabricated
  - each destination hub's label is always 0: it represents shared
    destination infrastructure (a server), not an attacker, under this
    dataset's star topology -- this modeling choice is stated here, not
    hidden

Rows are grouped into fixed-size windows (`--window-size`, default 500); each
window becomes one graph sample (one JSON line), so the resulting dataset is
exactly the `dataset.load_dataset()` JSON-lines format
`services/ml-training/src/sm_ml_training/dataset.py` already expects:
`{"nodes": [...], "edges": [...], "labels": {...}}` per line.

Determinism: output depends only on the input file's bytes and
`--window-size`. The output file's own sha256 is printed so a training run
can record which exact derived-dataset bytes it used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_DURATION = 0
_LABEL_COL = 41
_N_COLS = 43

_DEST_POOL = tuple(f"10.60.0.{n}" for n in range(1, 17))


def _read_rows(path: Path) -> list[list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"NSL-KDD file not found: {path}")
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != _N_COLS:
            raise ValueError(f"expected {_N_COLS} columns, got {len(parts)}: {line[:80]!r}")
        rows.append(parts)
    if not rows:
        raise ValueError(f"no rows read from {path}")
    return rows


def _window_to_sample(rows: list[list[str]], start_index: int, window_start_t: float) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    labels: dict[str, int] = {}

    for offset, row in enumerate(rows):
        index = start_index + offset
        src_id = f"10.50.{(index // 256) % 256}.{index % 256}"
        dst_id = _DEST_POOL[index % len(_DEST_POOL)]
        t = window_start_t + float(offset)
        duration = float(row[_DURATION])
        is_attack = 0 if row[_LABEL_COL] == "normal" else 1

        if src_id not in nodes:
            nodes[src_id] = {
                "node_id": src_id, "node_type": "IpAddress",
                "first_seen": t, "last_seen": t + max(duration, 0.0),
            }
        labels[src_id] = is_attack  # one src node per row: no label conflict possible

        if dst_id not in nodes:
            nodes[dst_id] = {"node_id": dst_id, "node_type": "IpAddress", "first_seen": t, "last_seen": t}
        else:
            nodes[dst_id]["last_seen"] = max(nodes[dst_id]["last_seen"], t)
        labels[dst_id] = 0  # shared destination infrastructure, not itself malicious

        edges.append({"src_id": src_id, "dst_id": dst_id, "edge_type": "CONNECTED_TO", "observed_at": t})

    return {"nodes": list(nodes.values()), "edges": edges, "labels": labels}


def build(in_path: Path, out_path: Path, *, window_size: int) -> tuple[int, int, int]:
    rows = _read_rows(in_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = 0
    n_attack_nodes = 0
    n_nodes_total = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for start in range(0, len(rows), window_size):
            chunk = rows[start : start + window_size]
            sample = _window_to_sample(chunk, start, float(start))
            n_attack_nodes += sum(sample["labels"].values())
            n_nodes_total += len(sample["nodes"])
            fh.write(json.dumps(sample, sort_keys=True, separators=(",", ":")))
            fh.write("\n")
            n_samples += 1
    return n_samples, n_nodes_total, n_attack_nodes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True, help="Real NSL-KDD file (e.g. KDDTrain+.txt)")
    ap.add_argument("--out", required=True, help="Output JSONL path")
    ap.add_argument("--window-size", type=int, default=500, help="Rows per graph sample (default 500)")
    args = ap.parse_args()

    in_path = Path(args.file)
    out_path = Path(args.out)
    n_samples, n_nodes, n_attack_nodes = build(in_path, out_path, window_size=args.window_size)
    out_sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    in_sha256 = hashlib.sha256(in_path.read_bytes()).hexdigest()

    print(f"source file:      {in_path} (sha256 {in_sha256})")
    print(f"source rows:       {sum(1 for _ in in_path.read_text(encoding='utf-8').splitlines() if _.strip())}")
    print(f"graph samples:     {n_samples} (window_size={args.window_size})")
    print(f"total nodes:       {n_nodes}")
    print(f"attack-labelled nodes: {n_attack_nodes}")
    print(f"output file:       {out_path} (sha256 {out_sha256})")


if __name__ == "__main__":
    main()
