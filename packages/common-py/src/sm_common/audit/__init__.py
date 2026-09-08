"""Audit logging.

The append-only, DB-bound `AuditWriter` lands with the ORM models in Phase 1,
Unit 3. The pure hash-chain primitives are available now.
"""

from __future__ import annotations

from .hashing import GENESIS_HASH, canonical_json, compute_entry_hash, verify_chain

__all__ = ["GENESIS_HASH", "canonical_json", "compute_entry_hash", "verify_chain"]
