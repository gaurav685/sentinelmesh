"""S3-compatible object storage (ADR-019). MinIO locally / S3-compatible in prod."""

from __future__ import annotations

from .s3 import ObjectStore, build_object_store_session, safe_key

__all__ = ["ObjectStore", "build_object_store_session", "safe_key"]
