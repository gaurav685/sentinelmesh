#!/usr/bin/env python3
"""Real end-to-end latency/throughput through `ml-inference`'s actual HTTP API
-- NOT the same thing `scripts/benchmark_inference_latency.py` measures.

That script times `GradientBoostingModel.score()` / `Booster.predict()`
called directly in a bare Python loop -- it never goes through the FastAPI
app, pydantic request/response validation, the internal-JWT auth dependency,
or the `ModelHost`/`ModelRegistry` lookup `/infer/{model}` actually performs
in production. This script does, by building the real `sm_ml_inference.app`
(`create_app`) and driving it with `fastapi.testclient.TestClient` -- the
exact same construction `services/ml-inference/tests/conftest.py` uses for
its own real request tests, not a mock.

**What this does NOT measure**: `TestClient` talks to the ASGI app via
httpx's in-process `ASGITransport` -- there is no real OS socket, no actual
TCP/TLS handshake, no network hop between a caller and this process. So this
number is real end-to-end *application* latency (routing, auth, pydantic
validation, the real model lookup and scoring, response serialization) but
excludes real network transport time, which would be additive on top of
this in an actual deployed multi-process/multi-host setup.

**No batch endpoint exists.** `POST /infer/{model}`'s `InferRequest.features`
is one flow's feature vector (`list[float]`, not a list of vectors) -- the
real production API scores exactly one flow per request. "Batch of 1000"
below is therefore 1000 real sequential HTTP calls to that same single-flow
endpoint, not one vectorised call -- labelled as such, not dressed up as a
batch endpoint that doesn't exist.

    python scripts/benchmark_inference_latency_e2e.py \
        --eval-file /c/Sentinel_Mesh/archive/KDDTest+.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

_N_COLS = 43
_PROTOCOL_TYPE = 1
_SRC_BYTES = 4
_DST_BYTES = 5
_TEST_JWT_KEY = "ml-inference-e2e-benchmark-signing-key-0123456789"


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
    from sm_common.ids import uuid7
    from sm_contracts import CanonicalEventPayload, CanonicalKind, EntityKind, EntityRef, EventType
    from sm_ml.features import extract_features

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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-file", required=True, help="Real NSL-KDD file to draw real feature rows from")
    ap.add_argument("--n-single", type=int, default=2000)
    ap.add_argument("--n-batch", type=int, default=1000, help="Sequential HTTP calls for the 'batch' number")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import os

    os.environ["SM_ML_ENABLE_GRADIENT_BOOSTING"] = "true"
    os.environ.setdefault("SM_ML_MODEL_DIR", "ml/artifacts")

    from fastapi.testclient import TestClient
    from sm_ml_inference.app import create_app

    from sm_common.config import AppSettings
    from sm_common.security import mint_internal_token
    from sm_contracts import CanonicalKind
    from sm_ml import schema_for

    settings = AppSettings(
        _env_file=None, service_name="ml-inference", pg_password="x",
        internal_jwt_signing_key=_TEST_JWT_KEY, oidc_client_secret="s", neo4j_password="x",
    )
    app = create_app(settings=settings)
    token = mint_internal_token(
        signing_key=_TEST_JWT_KEY, subject="detection-engine", tenant_id=uuid.uuid4(), audience="ml-inference",
    )
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(UTC)
    needed = args.n_single + args.n_batch
    rows = _read_rows(Path(args.eval_file), needed)
    vectors = [_row_to_vector(rows[i % len(rows)], now) for i in range(needed)]

    schema_version = schema_for(CanonicalKind.network_flow).version

    def _body(features: list[float]) -> dict[str, object]:
        return {
            "kind": CanonicalKind.network_flow.value,
            "feature_schema_version": schema_version,
            "features": features,
        }

    with TestClient(app) as client:
        # one real call first, outside the timed loop, to confirm the model
        # is actually served (flag + artifact both real) before trusting any
        # timing below -- a 503 here means the numbers below would be
        # measuring an error path, not real inference.
        warm = client.post("/api/v1/infer/gradient_boosting_network_flow", json=_body(vectors[0]), headers=headers)
        if warm.status_code != 200:
            raise RuntimeError(
                f"model not served (status {warm.status_code}, body {warm.text}) -- "
                "SM_ML_ENABLE_GRADIENT_BOOSTING or the artifact dir is wrong; refusing to report fake latency"
            )

        single_latencies_ms: list[float] = []
        t_start = time.perf_counter()
        for v in vectors[: args.n_single]:
            t0 = time.perf_counter()
            r = client.post("/api/v1/infer/gradient_boosting_network_flow", json=_body(v), headers=headers)
            single_latencies_ms.append((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                raise RuntimeError(f"unexpected status {r.status_code}: {r.text}")
        single_total_s = time.perf_counter() - t_start
        single_latencies_ms.sort()

        batch_latencies_ms: list[float] = []
        offset = args.n_single
        t_start = time.perf_counter()
        for v in vectors[offset : offset + args.n_batch]:
            t0 = time.perf_counter()
            r = client.post("/api/v1/infer/gradient_boosting_network_flow", json=_body(v), headers=headers)
            batch_latencies_ms.append((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                raise RuntimeError(f"unexpected status {r.status_code}: {r.text}")
        batch_total_s = time.perf_counter() - t_start
        batch_latencies_ms.sort()

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "what_this_measures": (
            "real sm_ml_inference FastAPI app via TestClient (ASGITransport, in-process -- "
            "no real OS socket/network hop), real routing+auth+pydantic validation+model lookup"
            "+scoring+serialization. NOT the same as scripts/benchmark_inference_latency.py's "
            "bare in-process model.score() loop."
        ),
        "endpoint": "POST /api/v1/infer/gradient_boosting_network_flow",
        "eval_file": args.eval_file,
        "n_single_requests": len(single_latencies_ms),
        "single_request_latency_ms": {
            "p50": _percentile(single_latencies_ms, 50), "p99": _percentile(single_latencies_ms, 99),
            "mean": sum(single_latencies_ms) / len(single_latencies_ms),
        },
        "single_request_throughput_requests_per_s": round(len(single_latencies_ms) / single_total_s, 1),
        "n_batch_requests": len(batch_latencies_ms),
        "batch_note": (
            "no batch endpoint exists -- InferRequest.features is one flow's vector, not a list "
            "of vectors, so 'batch' here is N real SEQUENTIAL HTTP calls to the same single-flow "
            "endpoint, not one vectorised call"
        ),
        "batch_sequential_latency_ms": {
            "p50": _percentile(batch_latencies_ms, 50), "p99": _percentile(batch_latencies_ms, 99),
        },
        "batch_sequential_throughput_requests_per_s": round(len(batch_latencies_ms) / batch_total_s, 1),
    }
    report_json = json.dumps(report, indent=2)
    print(report_json)
    if args.out:
        Path(args.out).write_text(report_json, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
