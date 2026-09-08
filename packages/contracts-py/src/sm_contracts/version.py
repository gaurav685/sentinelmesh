"""Contract package version.

Bumped on any breaking change to a STABLE contract. DRAFT contracts may change
without a bump until first implementation (see docs/CONTRACTS.md).
"""

from __future__ import annotations

CONTRACTS_VERSION = "0.1.0"
"""Semantic version of the SentinelMesh contract set."""

ENVELOPE_SCHEMA_VERSION = 1
"""Version of the canonical event envelope structure itself (not per-payload)."""
