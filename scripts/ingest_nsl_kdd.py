#!/usr/bin/env python3
"""Replay real NSL-KDD rows through the real ingestion pipeline (Phase 18).

    python scripts/ingest_nsl_kdd.py \
        --file /c/Sentinel_Mesh/archive/KDDTest+.txt \
        --sensor-credential "<sensor_id>.<secret>" \
        --limit 200

Each row is a real, labelled network-connection record from the public
NSL-KDD dataset (not synthetic -- no `simulated` flag is set on anything
this script sends). Real fields (`duration`, `protocol_type`, `service`,
`flag`, `src_bytes`, `dst_bytes`) map directly onto
`NetworkFlowPayload`; the pipeline is never told the dataset's own label
(`normal`/`neptune`/...) -- that's printed locally afterward as ground
truth to compare against whatever the real detection pipeline actually
decides, not fed in as a hint.

NSL-KDD limitations, stated rather than silently worked around:
  - The dataset carries no real IP addresses (a known property of this
    derived/anonymized dataset, not something this script strips out).
    Placeholder IPs are synthesized deterministically from the row index
    (`10.50.<row//256>.<row%256>` / a fixed small pool of destinations) so
    the payload's schema-required src_ip/dst_ip are present -- clearly a
    placeholder, never presented as a captured address.
  - The dataset carries no real capture timestamp either. Each row is
    stamped with the actual wall-clock time this script sends it (spaced
    `--interval-s` apart), which is honestly "when this replay happened,"
    not a fabricated 1999-era capture time.

Posts in batches of up to `SM_INGEST_BATCH_MAX_EVENTS` (default 500) via
`POST /api/v1/ingest/batch`. Target api-gateway is `--base-url`
(default http://localhost:8000), matching the local docker-compose port.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_LABEL_COL = 41
_DIFFICULTY_COL = 42
_N_COLS = 43  # 41 features + label + difficulty

# Row layout, 0-indexed (kddcup.names ordering, as used by NSL-KDD).
_DURATION = 0
_PROTOCOL_TYPE = 1
_SERVICE = 2
_FLAG = 3
_SRC_BYTES = 4
_DST_BYTES = 5

_DEST_POOL = tuple(f"10.60.0.{n}" for n in range(1, 17))  # 16 fixed synthetic "servers"


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


def _to_payload(row: list[str], index: int, occurred_at: datetime) -> dict[str, Any]:
    duration_s = float(row[_DURATION])
    src_bytes = int(row[_SRC_BYTES])
    dst_bytes = int(row[_DST_BYTES])
    payload: dict[str, Any] = {
        "occurred_at": occurred_at.isoformat(),
        "src_ip": f"10.50.{(index // 256) % 256}.{index % 256}",
        "dst_ip": _DEST_POOL[index % len(_DEST_POOL)],
        "protocol": row[_PROTOCOL_TYPE],
        "app_protocol": row[_SERVICE],
        "bytes_sent": src_bytes,
        "bytes_received": dst_bytes,
        "verdict": row[_FLAG],
    }
    if duration_s > 0:
        payload["ended_at"] = (occurred_at + timedelta(seconds=duration_s)).isoformat()
    return payload


def _post(url: str, body: dict[str, Any], credential: str) -> dict[str, Any]:
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 -- scheme checked above
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": credential},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 -- scheme checked above
            return dict(json.loads(resp.read()))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="Path to a real NSL-KDD file (e.g. KDDTest+.txt)")
    ap.add_argument("--sensor-credential", required=True, help="<sensor_id>.<secret> from seed_demo.py")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--limit", type=int, default=200, help="Rows to send (default 200; the full test split is 22544)")
    ap.add_argument("--batch-size", type=int, default=100, help="Events per POST /ingest/batch call")
    ap.add_argument("--interval-s", type=float, default=0.05, help="Simulated spacing between each row's occurred_at")
    args = ap.parse_args()

    rows = _read_rows(Path(args.file), args.limit)
    print(f"read {len(rows)} real NSL-KDD rows from {args.file}")

    now = datetime.now(UTC)
    ground_truth = Counter(row[_LABEL_COL] for row in rows)
    print("dataset's own ground-truth labels (NOT sent to the pipeline):")
    for label, count in ground_truth.most_common():
        print(f"  {label}: {count}")

    url = f"{args.base_url}/api/v1/ingest/batch"
    accepted_total = 0
    rejected_total = 0
    for start in range(0, len(rows), args.batch_size):
        chunk = rows[start : start + args.batch_size]
        events = [
            _to_payload(row, start + i, now + timedelta(seconds=(start + i) * args.interval_s))
            for i, row in enumerate(chunk)
        ]
        result = _post(url, {"source_type": "network_flow", "events": events}, args.sensor_credential)
        accepted_total += int(result.get("accepted", 0))
        rejected = result.get("rejected", [])
        rejected_total += len(rejected)
        if rejected:
            print(f"  batch at row {start}: {len(rejected)} rejected -- {rejected[:3]}")
        print(f"  sent rows {start}..{start + len(chunk) - 1}: accepted={result.get('accepted')}")
        time.sleep(0.05)

    print()
    print(f"done: {accepted_total} accepted, {rejected_total} rejected, out of {len(rows)} real rows.")
    print("Check detections for real (non-simulated) rows via:")
    print("  GET /api/v1/soc/detections  (any row here has no \"simulated\" flag at all)")


if __name__ == "__main__":
    main()
