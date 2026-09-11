"""Deterministic feature vectors for threat-memory similarity (Phase 13).

`technique_feature_vector` is a **hashed bag-of-techniques** vector — a fixed
dimension, L2-normalized histogram over `sha256(technique_id) % dim` buckets.
It is not a trained embedding and no semantic claim is made beyond "campaigns
sharing techniques land closer together" — the same non-fabrication stance the
rest of the platform takes toward anything ML-shaped (Constitution §3, §13).
Standard-library, deterministic, and a pure function of its input.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

__all__ = ["FEATURE_VECTOR_DIM", "cosine_similarity", "technique_feature_vector"]

FEATURE_VECTOR_DIM = 32


def technique_feature_vector(
    technique_ids: Sequence[str], *, dim: int = FEATURE_VECTOR_DIM
) -> list[float]:
    """L2-normalized counts of `technique_ids` over `dim` hash buckets. An
    empty input is the zero vector (never similar to anything, including
    itself under cosine similarity — callers should treat that as "no
    signal", not a match)."""
    if dim < 1:
        raise ValueError("dim must be >= 1")
    counts = [0.0] * dim
    for tid in technique_ids:
        bucket = int(hashlib.sha256(tid.encode("utf-8")).hexdigest(), 16) % dim
        counts[bucket] += 1.0
    norm = math.sqrt(sum(c * c for c in counts))
    if norm == 0.0:
        return counts
    return [c / norm for c in counts]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """`[-1, 1]`; `0.0` when either vector has no signal (the zero vector) —
    the exact-match fallback path used when pgvector is unavailable."""
    if len(a) != len(b):
        raise ValueError("vectors must be the same length")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
