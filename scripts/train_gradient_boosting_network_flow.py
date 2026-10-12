#!/usr/bin/env python3
"""Train and export a real LightGBM artifact for `gradient_boosting_network_flow`.

    python scripts/train_gradient_boosting_network_flow.py \
        --train-file /c/Sentinel_Mesh/archive/KDDTrain+.txt \
        --out ml/artifacts/gradient_boosting_network_flow/v1

Feature extraction reuses this repo's own real, production
`sm_ml.features.extract_features` -- the exact function detection-engine
calls at inference time -- via the exact same NSL-KDD-row -> attributes
mapping `scripts/train_isolation_forest_network_flow.py` already uses, so
train/serve skew is structural, not just intended. Same honest limitation
as that script: NSL-KDD provides no destination port, packet counts, or
direction, so 5 of this schema's 8 real features are constant zero here.

Unlike Isolation Forest/the autoencoder, LightGBM is SUPERVISED --
NSL-KDD's real normal/attack label is used to fit it directly (not just
for an optional held-out sanity check), a real, structural difference
from this project's other two production network-flow models, stated
plainly rather than blended into their "unsupervised" framing.

This is a SEPARATE model from the Phase 1 CICIDS2017/UNSW-NB15 LightGBM
comparison (`services/ml-training/src/sm_ml_training/benchmark/`) --
those are trained on 78/193-dim public-dataset feature schemas for an
academic benchmark and were never intended to be served; this one is
trained on the platform's own real 8-dim `NetworkFlowPayload` schema so
it can actually be loaded by `sm_ml.registry.ModelRegistry` and served
through `ml-inference`'s `/infer/{model}`, behind the
`SM_ML_ENABLE_GRADIENT_BOOSTING` flag (see `docs/models/gradient_boosting_network_flow.md`).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sm_common.ids import uuid7
from sm_contracts import CanonicalEventPayload, CanonicalKind, EntityKind, EntityRef, EventType
from sm_ml.features import extract_features
from sm_ml.models.gradient_boosting import GradientBoostingModel

_LABEL_COL = 41
_DIFFICULTY_COL = 42
_N_COLS = 43
_PROTOCOL_TYPE = 1
_SRC_BYTES = 4
_DST_BYTES = 5

MODEL_NAME = "gradient_boosting_network_flow"
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
    """Real NSL-KDD row -> the exact real feature vector `extract_features`
    would produce for the equivalent live event -- same mapping
    `train_isolation_forest_network_flow.py` uses."""
    actor = EntityRef(kind=EntityKind.ip, value="10.50.0.1")
    target = EntityRef(kind=EntityKind.ip, value="10.60.0.1")
    canonical = CanonicalEventPayload(
        kind=CanonicalKind.network_flow,
        occurred_at=now,
        action="connected_to",
        outcome=row[3],
        actor=actor,
        target=target,
        entities=[actor, target],
        raw_event_id=uuid7(),
        raw_event_type=EventType.telemetry_network_flow,
        attributes={
            "protocol": row[_PROTOCOL_TYPE],
            "bytes_sent": int(row[_SRC_BYTES]),
            "bytes_received": int(row[_DST_BYTES]),
        },
    )
    return extract_features(canonical).vector


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-file", required=True)
    ap.add_argument("--eval-file", default=None, help="Optional labelled file for a held-out sanity check")
    ap.add_argument("--out", required=True, help="Output dir, e.g. ml/artifacts/gradient_boosting_network_flow/v1")
    ap.add_argument("--limit", type=int, default=None, help="Cap training rows (default: use the whole file)")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    now = datetime.now(UTC)
    train_rows = _read_rows(Path(args.train_file), args.limit)
    print(f"read {len(train_rows)} real NSL-KDD training rows from {args.train_file}")

    x_train = [_row_to_vector(r, now) for r in train_rows]
    y_train = [0 if r[_LABEL_COL] == "normal" else 1 for r in train_rows]
    n_attack = sum(y_train)
    print(f"real label distribution: {len(y_train) - n_attack} normal, {n_attack} attack")

    feature_names = extract_features(
        CanonicalEventPayload(
            kind=CanonicalKind.network_flow, occurred_at=now, action="connected_to",
            raw_event_id=uuid4(), raw_event_type=EventType.telemetry_network_flow, attributes={},
        )
    ).names
    feature_schema_version = extract_features(
        CanonicalEventPayload(
            kind=CanonicalKind.network_flow, occurred_at=now, action="connected_to",
            raw_event_id=uuid4(), raw_event_type=EventType.telemetry_network_flow, attributes={},
        )
    ).schema_version

    model = GradientBoostingModel.fit(
        feature_names, x_train, y_train, seed=args.seed, model_version=MODEL_VERSION, threshold=args.threshold,
    )

    out_dir = Path(args.out)
    model.save(out_dir)
    metadata_path = out_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["feature_schema_version"] = feature_schema_version
    metadata["task"] = "anomaly_score"
    metadata["trained_on"] = {
        "dataset": "NSL-KDD (public)", "file": str(args.train_file),
        "row_count": len(train_rows), "n_attack": n_attack, "trained_at": now.isoformat(),
    }
    metadata["known_limitations"] = (
        "NSL-KDD provides no dst_port, packet counts, or direction -- those 5 of 8 "
        "feature dimensions are constant zero in this training set and at inference "
        "time for data replayed from it. Unlike isolation_forest_network_flow and "
        "autoencoder_network_flow, this model is SUPERVISED: it was fit directly on "
        "NSL-KDD's real normal/attack label, not just evaluated against it."
    )
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'model.txt'} and {metadata_path}")

    if args.eval_file:
        eval_rows = _read_rows(Path(args.eval_file), args.limit)
        x_eval = [_row_to_vector(r, now) for r in eval_rows]
        y_eval_true = [r[_LABEL_COL] != "normal" for r in eval_rows]
        scores = [model.score(row) for row in x_eval]
        predicted_anomaly = [s.is_anomaly for s in scores]
        tp = sum(1 for p, y in zip(predicted_anomaly, y_eval_true, strict=True) if p and y)
        fp = sum(1 for p, y in zip(predicted_anomaly, y_eval_true, strict=True) if p and not y)
        fn = sum(1 for p, y in zip(predicted_anomaly, y_eval_true, strict=True) if not p and y)
        tn = sum(1 for p, y in zip(predicted_anomaly, y_eval_true, strict=True) if not p and not y)
        print()
        print(
            f"held-out sanity check on {args.eval_file} ({len(eval_rows)} rows, "
            "real labels, same split pattern as the other two network-flow models):"
        )
        print(f"  tp={tp} fp={fp} fn={fn} tn={tn}")
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"  precision={precision:.3f} recall={recall:.3f}")


if __name__ == "__main__":
    main()
    sys.exit(0)
