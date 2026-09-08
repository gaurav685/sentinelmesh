"""Audit hash chain (Engineering Constitution §5; security-model.md §8).

Each tenant's audit log is a hash chain: `hash(n) = sha256(hash(n-1) ‖
canonical(row_n))`. A gap or an altered row breaks the chain, making tampering
detectable. This module is pure — the DB-bound `AuditWriter` (Phase 1, Unit 3,
alongside the ORM models) uses it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["GENESIS_HASH", "canonical_json", "compute_entry_hash", "verify_chain"]

GENESIS_HASH = "0" * 64
"""`prev_hash` for the first entry in a tenant's chain."""


def canonical_json(row: dict[str, Any]) -> bytes:
    """Deterministic serialization: sorted keys, no insignificant whitespace,
    UTF-8. The same logical row always produces the same bytes."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode(
        "utf-8"
    )


def compute_entry_hash(prev_hash: str, row: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(b"\x1e")  # record separator, so concatenation is unambiguous
    h.update(canonical_json(row))
    return h.hexdigest()


def verify_chain(entries: list[tuple[str, dict[str, Any]]], *, genesis: str = GENESIS_HASH) -> bool:
    """`entries` is an ordered list of `(stored_hash, row)`. Returns True if every
    stored hash equals the recomputed hash for that position."""
    prev = genesis
    for stored_hash, row in entries:
        expected = compute_entry_hash(prev, row)
        if expected != stored_hash:
            return False
        prev = stored_hash
    return True
