"""Feature preprocessing (versioned, deterministic, numpy-free)."""

from __future__ import annotations

from .scaler import PREPROCESSING_VERSION, Preprocessor

__all__ = ["PREPROCESSING_VERSION", "Preprocessor"]
