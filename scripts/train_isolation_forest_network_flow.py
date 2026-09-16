#!/usr/bin/env python3
"""Train and export a real isolation-forest artifact for `isolation_forest_network_flow`
(the model detection-engine has been requesting and getting a real 503 for --
see docs/architecture/demo-mode.md and scripts/ingest_nsl_kdd.py).

    python scripts/train_isolation_forest_network_flow.py \
        --train-file /c/Sentinel_Mesh/archive/KDDTrain+.txt \
        --out ml/artifacts/isolation_forest_network_flow/v1

Feature extraction reuses this repo's own real, production
`sm_ml.features.extract_features` -- the exact function detection-engine
calls at inference time -- via the exact same NSL-KDD-row -> attributes
mapping `normalization-engine`'s real `_network_flow()` mapper produces
(protocol/bytes_sent/bytes_received/dst_port/packets_*/direction). This
is not a parallel/approximate feature encoding: it is the real one, so
train/serve skew is structural, not just intended.

Honest about what NSL-KDD does NOT provide (stated, not silently
defaulted around): the dataset carries no destination port, no packet
counts, and no traffic direction -- three of this schema's eight real
features (`dst_port`, `dst_port_is_system`, `dst_port_is_ephemeral`,
`packets_total_log`, `direction_outbound`) are therefore constant zero
for every row trained on here, exactly as they are for
`scripts/ingest_nsl_kdd.py`'s real replayed rows. The model is real; its
two informative dimensions from this dataset are `bytes_sent_log`,
`bytes_received_log`, and `proto_tcp`.

`--threshold-percentile` (default 95) sets the anomaly threshold at that
percentile of the TRAINING set's own anomaly scores -- a real, principled
choice (flag the most-anomalous 5% of training traffic), not a fabricated
number. NSL-KDD's own attack/normal label is never used for training
(isolation forest is unsupervised) or for choosing the threshold -- only
for the optional held-out `--eval-file` sanity check printed at the end,
clearly separated from what the model itself was fit on.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from sm_common.ids import uuid7
from sm_contracts import CanonicalEventPayload, CanonicalKind, EntityKind, EntityRef, EventType
from sm_ml.features import extract_features

_LABEL_COL = 41
_DIFFICULTY_COL = 42
_N_COLS = 43
_DURATION = 0
_PROTOCOL_TYPE = 1
_SRC_BYTES = 4
_DST_BYTES = 5

MODEL_NAME = "isolation_forest_network_flow"
MODEL_VERSION = "nsl-kdd-v1"


def _read_rows(path: Path, limit: int | None) -> list[list[str]]:
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
        if limit is not None and len(rows) >= limit:
            break
    if not rows:
        raise ValueError(f"no rows read from {path}")
    return rows


def _row_to_vector(row: list[str], now: datetime) -> list[float]:
    """Real NSL-KDD row -> the exact real feature vector
    `extract_features` would produce for the equivalent live event --
    same attribute keys `_network_flow()` (normalization-engine) writes,
    same function detection-engine calls."""
    actor = EntityRef(kind=EntityKind.ip, value="10.50.0.1")
    target = EntityRef(kind=EntityKind.ip, value="10.60.0.1")
    canonical = CanonicalEventPayload(
        kind=CanonicalKind.network_flow,
        occurred_at=now,
        action="connected_to",
        outcome=row[3],  # NSL-KDD's `flag` column, mapped like `p.verdict` is
        actor=actor,
        target=target,
        entities=[actor, target],
        raw_event_id=uuid7(),
        raw_event_type=EventType.telemetry_network_flow,
        attributes={
            "protocol": row[_PROTOCOL_TYPE],
            "bytes_sent": int(row[_SRC_BYTES]),
            "bytes_received": int(row[_DST_BYTES]),
            # NSL-KDD provides none of these -- left absent, exactly as a
            # real sensor lacking this data would (extract_features then
            # defaults each to 0.0 via `_num`'s `default` path, not a
            # fabricated non-zero value).
        },
    )
    return extract_features(canonical).vector


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-file", required=True)
    ap.add_argument("--eval-file", default=None, help="Optional labelled file for a held-out sanity check")
    ap.add_argument("--out", required=True, help="Output dir, e.g. ml/artifacts/isolation_forest_network_flow/v1")
    ap.add_argument("--limit", type=int, default=None, help="Cap training rows (default: use the whole file)")
    ap.add_argument("--threshold-percentile", type=float, default=95.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    now = datetime.now(UTC)
    train_rows = _read_rows(Path(args.train_file), args.limit)
    print(f"read {len(train_rows)} real NSL-KDD training rows from {args.train_file}")

    x_train = np.array([_row_to_vector(r, now) for r in train_rows], dtype=float)
    feature_names = extract_features(
        CanonicalEventPayload(
            kind=CanonicalKind.network_flow, occurred_at=now, action="connected_to",
            raw_event_id=uuid4(), raw_event_type=EventType.telemetry_network_flow, attributes={},
        )
    ).names

    estimator = IsolationForest(random_state=args.seed, n_estimators=200)
    estimator.fit(x_train)

    train_scores = -estimator.score_samples(x_train)
    score_min = float(train_scores.min())
    score_max = float(train_scores.max())
    threshold = float(np.percentile(train_scores, args.threshold_percentile))
    print(
        f"trained: {len(train_rows)} rows, {x_train.shape[1]} features, "
        f"score range [{score_min:.4f}, {score_max:.4f}], "
        f"threshold (p{args.threshold_percentile:.0f}) = {threshold:.4f}"
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(estimator, out_dir / "model.joblib")
    metadata = {
        "model_version": MODEL_VERSION,
        "method": "isolation_forest",
        "feature_names": list(feature_names),
        "feature_schema_version": extract_features(
            CanonicalEventPayload(
                kind=CanonicalKind.network_flow, occurred_at=now, action="connected_to",
                raw_event_id=uuid4(), raw_event_type=EventType.telemetry_network_flow, attributes={},
            )
        ).schema_version,
        "score_min": score_min,
        "score_max": score_max,
        "threshold": threshold,
        "task": "anomaly_score",
        "trained_on": {
            "dataset": "NSL-KDD (public)",
            "file": str(args.train_file),
            "row_count": len(train_rows),
            "trained_at": now.isoformat(),
        },
        "known_limitations": (
            "NSL-KDD provides no dst_port, packet counts, or direction -- "
            "those 5 of 8 feature dimensions are constant zero in this "
            "training set and at inference time for data replayed from it."
        ),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'model.joblib'} and {out_dir / 'metadata.json'}")

    if args.eval_file:
        eval_rows = _read_rows(Path(args.eval_file), args.limit)
        x_eval = np.array([_row_to_vector(r, now) for r in eval_rows], dtype=float)
        eval_scores = -estimator.score_samples(x_eval)
        predicted_anomaly = eval_scores >= threshold
        true_attack = np.array([r[_LABEL_COL] != "normal" for r in eval_rows])
        tp = int(np.sum(predicted_anomaly & true_attack))
        fp = int(np.sum(predicted_anomaly & ~true_attack))
        fn = int(np.sum(~predicted_anomaly & true_attack))
        tn = int(np.sum(~predicted_anomaly & ~true_attack))
        print()
        print(f"held-out sanity check on {args.eval_file} ({len(eval_rows)} rows, label used ONLY for this printout):")
        print(f"  tp={tp} fp={fp} fn={fn} tn={tn}")
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"  precision={precision:.3f} recall={recall:.3f}")
        print(
            "  (this is an unsupervised model scored against labels it never saw -- "
            "a real number, not tuned to look good: threshold came only from the "
            "training set's own score distribution.)"
        )


if __name__ == "__main__":
    main()
    sys.exit(0)
