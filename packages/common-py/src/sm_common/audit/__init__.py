"""Audit logging: hash-chain primitives and the append-only writer."""

from __future__ import annotations

from .hashing import GENESIS_HASH, canonical_json, compute_entry_hash, verify_chain
from .writer import PLATFORM_LOCK_KEY, AuditWriter

__all__ = [
    "GENESIS_HASH",
    "PLATFORM_LOCK_KEY",
    "AuditWriter",
    "canonical_json",
    "compute_entry_hash",
    "verify_chain",
]
