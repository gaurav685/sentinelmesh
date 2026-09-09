"""Versioned feature schemas + deterministic extractors."""

from __future__ import annotations

from .extract import FeatureVector, extract_features, shannon_entropy
from .schema import (
    FEATURE_SCHEMA_VERSION,
    FEATURE_SCHEMAS,
    FeatureSchema,
    FeatureSpec,
    schema_for,
)

__all__ = [
    "FEATURE_SCHEMAS",
    "FEATURE_SCHEMA_VERSION",
    "FeatureSchema",
    "FeatureSpec",
    "FeatureVector",
    "extract_features",
    "schema_for",
    "shannon_entropy",
]
