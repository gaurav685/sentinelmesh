"""Parse a real, public NSL-KDD dataset file into ingest-ready payloads
(Phase 18 follow-up).

Pure functions -- no I/O, no auth, no HTTP. `routes/datasets.py` is the only
caller; kept separate so the exact same real mapping used by
`scripts/ingest_nsl_kdd.py` and `scripts/train_isolation_forest_network_flow.py`
lives in one place instead of three subtly-different copies.

NSL-KDD limitations, stated rather than silently worked around: the dataset
carries no real IP address and no real capture timestamp. Placeholder IPs are
synthesized deterministically from the row index; each row is stamped with the
real wall-clock time this parse happened, spaced apart -- honestly "when this
was replayed," never a fabricated historical capture time.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = ["NslKddParseError", "ParsedNslKdd", "parse_nsl_kdd"]

_N_COLS = 43  # 41 features + label + difficulty
_LABEL_COL = 41
_DURATION = 0
_PROTOCOL_TYPE = 1
_SERVICE = 2
_FLAG = 3
_SRC_BYTES = 4
_DST_BYTES = 5

_DEST_POOL = tuple(f"10.60.0.{n}" for n in range(1, 17))
_MAX_ROWS = 2_000  # a web upload is a demo/analyst action, not a bulk loader


class NslKddParseError(ValueError):
    """The uploaded file is not a well-formed NSL-KDD file."""


@dataclass(frozen=True)
class ParsedNslKdd:
    rows_read: int
    ground_truth_labels: dict[str, int]
    events: list[dict[str, Any]]  # NetworkFlowPayload-shaped, ready for /ingest/batch


def parse_nsl_kdd(raw: bytes, *, limit: int = _MAX_ROWS) -> ParsedNslKdd:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NslKddParseError(f"not a text file: {exc}") from exc

    limit = min(limit, _MAX_ROWS)
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != _N_COLS:
            raise NslKddParseError(
                f"expected {_N_COLS} comma-separated columns (the real NSL-KDD "
                f"format), got {len(parts)} in a row"
            )
        rows.append(parts)
        if len(rows) >= limit:
            break
    if not rows:
        raise NslKddParseError("no rows found in the uploaded file")

    now = datetime.now(UTC)
    events: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        duration_s = float(row[_DURATION])
        occurred_at = now + timedelta(seconds=i * 0.05)
        event: dict[str, Any] = {
            "occurred_at": occurred_at.isoformat(),
            "src_ip": f"10.50.{(i // 256) % 256}.{i % 256}",
            "dst_ip": _DEST_POOL[i % len(_DEST_POOL)],
            "protocol": row[_PROTOCOL_TYPE],
            "app_protocol": row[_SERVICE],
            "bytes_sent": int(row[_SRC_BYTES]),
            "bytes_received": int(row[_DST_BYTES]),
            "verdict": row[_FLAG],
        }
        if duration_s > 0:
            event["ended_at"] = (occurred_at + timedelta(seconds=duration_s)).isoformat()
        events.append(event)

    ground_truth = Counter(row[_LABEL_COL] for row in rows)
    return ParsedNslKdd(
        rows_read=len(rows), ground_truth_labels=dict(ground_truth), events=events
    )
