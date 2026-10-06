#!/usr/bin/env python3
"""Evaluate a real trained GNN checkpoint against a held-out graph dataset
(remediation item 9: "run the existing reproducible benchmark harness").

    python scripts/evaluate_gnn_checkpoint.py \
        --checkpoint ml/artifacts/graph/graphsage_0.1.0+a9de8a436ada.pt \
        --conv sage --hidden-dim 32 \
        --dataset ml/datasets/nsl-kdd-graph/test.jsonl

Reuses `sm_ml_training.benchmark.metrics` (ROC-AUC, precision/recall/F1/FPR)
-- the exact same stdlib-only, from-first-principles metric code the
tabular Isolation Forest / statistical benchmark already uses (task item 19:
"do not create an unrelated benchmark framework") -- rather than a parallel
scoring implementation, so a GNN number and a tabular number are computed
by literally the same formula.

ROC-AUC is computed from the model's RAW reconstruction-error score (not the
fixed `is_anomaly` cutoff `sm_ml.graph.models.gnn._ANOMALY_THRESHOLD = 0.8`
hardcodes) because ROC-AUC is threshold-free by definition. Precision/
recall/F1/FPR ARE computed from that fixed cutoff, because that is the real,
shipped serving behaviour -- not because it is a good threshold. This is
reported, not hidden: unlike every tabular model in this platform (Isolation
Forest's threshold = a real percentile of training scores; the statistical
model's z_threshold = a real grid search), the GNN boundary's anomaly cutoff
is a static architectural constant, never calibrated against this or any
dataset. A low recall below is therefore a property of an uncalibrated
cutoff, not necessarily of the embedding quality -- both are reported so
the difference is visible, not fabricated into a single misleading number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sm_ml.graph.construct import GraphEdge, GraphNode, build_graph_sample
from sm_ml.graph.models.gnn import (
    _ANOMALY_THRESHOLD,
    GAT_SPEC,
    GRAPHSAGE_SPEC,
    GnnNodeAnomalyModel,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "ml-training" / "src"))
from sm_ml_training.benchmark.metrics import precision_recall_f1_fpr, roc_auc


def _load_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
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
        yield build_graph_sample(nodes, edges), labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--conv", required=True, choices=["sage", "gat"])
    ap.add_argument("--hidden-dim", type=int, default=32)
    ap.add_argument("--dataset", required=True, type=Path)
    args = ap.parse_args()

    base_spec = GRAPHSAGE_SPEC if args.conv == "sage" else GAT_SPEC
    spec = type(base_spec)(
        name=base_spec.name, conv=base_spec.conv, hidden_dim=args.hidden_dim,
        num_layers=base_spec.num_layers, dropout=base_spec.dropout, heads=base_spec.heads,
    )
    model = GnnNodeAnomalyModel(spec=spec, model_version="eval", checkpoint=args.checkpoint)

    all_scores: list[float] = []
    all_preds: list[int] = []
    all_labels: list[int] = []
    n_samples = 0
    for sample, labels in _load_jsonl(args.dataset):
        n_samples += 1
        result = model.score_nodes(sample)
        for score in result.scores:
            all_scores.append(score.normalized_score)
            all_preds.append(1 if score.is_anomaly else 0)
            all_labels.append(labels[score.node_id])

    print(f"checkpoint: {args.checkpoint}")
    print(f"dataset:    {args.dataset} ({n_samples} samples, {len(all_labels)} nodes, "
          f"{sum(all_labels)} labelled anomalous)")
    print(f"fixed anomaly cutoff (never calibrated against this dataset): {_ANOMALY_THRESHOLD}")

    try:
        auc = roc_auc(all_scores, all_labels)
        print(f"roc_auc (threshold-free, from raw normalized score): {auc:.6f}")
    except ValueError as exc:
        print(f"roc_auc: NOT COMPUTABLE ({exc})")

    m = precision_recall_f1_fpr(all_preds, all_labels)
    print(f"precision={m['precision']:.6f} recall={m['recall']:.6f} "
          f"f1={m['f1']:.6f} fpr={m['false_positive_rate']:.6f}  "
          f"(at the fixed, uncalibrated {_ANOMALY_THRESHOLD} cutoff)")


if __name__ == "__main__":
    main()
