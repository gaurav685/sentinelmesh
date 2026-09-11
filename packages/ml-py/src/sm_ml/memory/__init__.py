"""Threat-memory feature vectors + similarity (Phase 13).

    technique_feature_vector(technique_ids) -> list[float]   (deterministic, L2-normalized)
    cosine_similarity(a, b)                 -> float in [-1, 1]

Standard-library. Not a trained embedding — see `features.py`.
"""

from __future__ import annotations

from .features import FEATURE_VECTOR_DIM, cosine_similarity, technique_feature_vector

__all__ = ["FEATURE_VECTOR_DIM", "cosine_similarity", "technique_feature_vector"]
