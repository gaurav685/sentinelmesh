#!/usr/bin/env python3
"""Real CPU inference latency/throughput benchmark for a loaded `AnomalyModel`
artifact -- `gradient_boosting_network_flow` by default, but any registry
artifact works via `--model-dir`.

Measures two genuinely different real code paths, not one number dressed up
as two:

1. **Single-request**: `model.score(features)` called once per row, in a
   loop -- the real one-event-at-a-time path `ml-inference`'s `/infer/{model}`
   actually takes in production.
2. **Batch of 1000**: the real LightGBM `Booster.predict()` call made ONCE on
   a 1000-row array -- the real vectorised path, not 1000 sequential
   single-row calls timed together (that number is also reported, labelled
   separately, so the real cost of NOT batching is visible too).

Feature vectors are real NSL-KDD test rows run through this repo's own real
`sm_ml.features.extract_features` (same mapping `scripts/train_*_network_flow.py`
use), not synthetic/random vectors -- so this measures the model actually
scoring realistic input, not an arbitrary float array.

    python scripts/benchmark_inference_latency.py \
        --model-dir ml/artifacts/gradient_boosting_network_flow/v1 \
        --eval-file /c/Sentinel_Mesh/archive/KDDTest+.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from sm_common.ids import uuid7
from sm_contracts import CanonicalEventPayload, CanonicalKind, EntityKind, EntityRef, EventType
from sm_ml.features import extract_features
from sm_ml.models.gradient_boosting import GradientBoostingModel

_N_COLS = 43
_PROTOCOL_TYPE = 1
_SRC_BYTES = 4
_DST_BYTES = 5


def _read_rows(path: Path, limit: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != _N_COLS:
            continue
        rows.append(parts)
        if len(rows) >= limit:
            break
    if not rows:
        raise ValueError(f"no rows read from {path}")
    return rows


def _row_to_vector(row: list[str], now: object) -> list[float]:
    actor = EntityRef(kind=EntityKind.ip, value="10.50.0.1")
    target = EntityRef(kind=EntityKind.ip, value="10.60.0.1")
    canonical = CanonicalEventPayload(
        kind=CanonicalKind.network_flow, occurred_at=now, action="connected_to", outcome=row[3],
        actor=actor, target=target, entities=[actor, target],
        raw_event_id=uuid7(), raw_event_type=EventType.telemetry_network_flow,
        attributes={
            "protocol": row[_PROTOCOL_TYPE], "bytes_sent": int(row[_SRC_BYTES]),
            "bytes_received": int(row[_DST_BYTES]),
        },
    )
    return extract_features(canonical).vector


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    idx = min(len(sorted_values) - 1, max(0, round(p / 100 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", default="ml/artifacts/gradient_boosting_network_flow/v1")
    ap.add_argument("--eval-file", required=True, help="Real NSL-KDD file to draw real feature rows from")
    ap.add_argument("--n-single", type=int, default=2000, help="Real single-request calls to time")
    ap.add_argument("--n-batches", type=int, default=30, help="Real batch-of-1000 calls to time")
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument("--out", default=None, help="Write the JSON report here (also still printed to stdout)")
    args = ap.parse_args()

    now = datetime.now(UTC)
    model = GradientBoostingModel.load(Path(args.model_dir))

    # Single-request loop consumes vectors[0:n_single); each of the two batch
    # loops independently re-consumes vectors[n_single:n_single+n_batches*batch_size)
    # starting from the same offset -- real total needed is the SUM of the two
    # streams, not their max (an earlier version of this script used max() here,
    # under-sized `vectors`, and silently fed LightGBM an empty/short final batch
    # -- found by actually running it, not assumed correct).
    needed = args.n_single + args.n_batches * args.batch_size
    rows = _read_rows(Path(args.eval_file), needed)
    # Cycle real rows if the file is shorter than needed -- still real feature
    # vectors, just reused, documented rather than silently truncating the ask.
    vectors = [_row_to_vector(rows[i % len(rows)], now) for i in range(needed)]

    print(f"loaded model from {args.model_dir}; {len(rows)} real rows read from {args.eval_file}")

    # --- 1. single-request path: model.score() called once per row ---
    single_latencies_ms: list[float] = []
    t_start = time.perf_counter()
    for v in vectors[: args.n_single]:
        t0 = time.perf_counter()
        model.score(v)
        single_latencies_ms.append((time.perf_counter() - t0) * 1000)
    single_total_s = time.perf_counter() - t_start
    single_latencies_ms.sort()

    # --- 2a. "1000 sequential single-row calls timed as a batch" ---
    seq_batch_latencies_ms: list[float] = []
    offset = args.n_single
    for _ in range(args.n_batches):
        batch = vectors[offset : offset + args.batch_size]
        offset += args.batch_size
        t0 = time.perf_counter()
        for v in batch:
            model.score(v)
        seq_batch_latencies_ms.append((time.perf_counter() - t0) * 1000)
    seq_batch_latencies_ms.sort()

    # --- 2b. real vectorised batch: one Booster.predict() call per batch ---
    import numpy as np

    vec_batch_latencies_ms: list[float] = []
    offset = args.n_single
    for _ in range(args.n_batches):
        batch = vectors[offset : offset + args.batch_size]
        offset += args.batch_size
        x = np.asarray(batch, dtype=float)
        t0 = time.perf_counter()
        model._booster.predict(x)
        vec_batch_latencies_ms.append((time.perf_counter() - t0) * 1000)
    vec_batch_latencies_ms.sort()

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model_dir": args.model_dir,
        "eval_file": args.eval_file,
        "n_single_requests": len(single_latencies_ms),
        "single_request_latency_ms": {
            "p50": _percentile(single_latencies_ms, 50), "p99": _percentile(single_latencies_ms, 99),
            "mean": sum(single_latencies_ms) / len(single_latencies_ms),
        },
        "single_request_throughput_flows_per_s": round(len(single_latencies_ms) / single_total_s, 1),
        "n_batches": len(seq_batch_latencies_ms), "batch_size": args.batch_size,
        "sequential_1000_calls_latency_ms": {
            "p50": _percentile(seq_batch_latencies_ms, 50), "p99": _percentile(seq_batch_latencies_ms, 99),
        },
        "vectorised_batch_predict_latency_ms": {
            "p50": _percentile(vec_batch_latencies_ms, 50), "p99": _percentile(vec_batch_latencies_ms, 99),
        },
        "vectorised_batch_throughput_flows_per_s": round(
            args.batch_size / (_percentile(vec_batch_latencies_ms, 50) / 1000), 1
        ),
    }
    report_json = json.dumps(report, indent=2)
    print(report_json)
    if args.out:
        Path(args.out).write_text(report_json, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
