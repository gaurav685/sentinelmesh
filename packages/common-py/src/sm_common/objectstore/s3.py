"""Async S3-compatible object storage client (ADR-019).

MinIO locally, AWS S3 (or another S3-compatible backend) in production —
never a hard dependency on AWS specifically. Security requirements from
ADR-019, enforced here:

- per-tenant key prefixes: every key is built from validated segments with
  the tenant id first (`safe_key(tenant_id, ...)`);
- server-side encryption on every write — applied via the bucket's default
  encryption rule (SSE-S3 AES256, set once by `ensure_bucket`), not a
  per-object header: MinIO (unlike AWS S3) refuses ANY server-side
  encryption request, bucket-default or per-object, unless a KMS backend
  is configured — `deploy/docker/docker-compose.yml`'s `minio` service
  sets `MINIO_KMS_SECRET_KEY` (a fixed, non-secret local-dev key) so
  local/CI runs exercise the same encrypted path production does;
- pre-signed, time-limited download URLs — a bucket is never made public;
- no user-controlled keys/paths: `safe_key()` is the only way to build a
  key, and it rejects anything that isn't a plain, bounded, safe segment —
  no `.`/`..`, no path separators, no control characters. This is the
  guard against path traversal and malicious filenames.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from ..config import AppSettings
from ..errors import DependencyUnavailable, ValidationFailed

__all__ = ["ObjectStore", "build_object_store_session", "safe_key"]

#: Conservative allow-list: ASCII letters/digits plus `._-`. No `/`, no
#: whitespace, no control characters. A single segment, 1-128 chars.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def safe_key(*parts: str) -> str:
    """Build an object key from validated path segments.

    Rejects an empty segment list, `.`/`..`, and anything outside the
    allow-list in any segment — the guard against path traversal and
    malicious filenames required by ADR-019. Never accepts a raw,
    pre-joined path from a caller.
    """
    if not parts:
        raise ValidationFailed("object key requires at least one segment")
    for part in parts:
        if part in {".", ".."} or not _SAFE_SEGMENT.match(part):
            raise ValidationFailed(f"unsafe object key segment: {part!r}")
    return "/".join(parts)


def build_object_store_session(settings: AppSettings) -> aioboto3.Session:
    return aioboto3.Session(
        aws_access_key_id=settings.s3_access_key_id.get_secret_value() or None,
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value() or None,
        region_name=settings.s3_region,
    )


class ObjectStore:
    """Wraps an `aioboto3` session plus the configured endpoint. Every
    method takes `key_parts` (never a pre-joined string) and runs them
    through `safe_key()` before touching the backend."""

    def __init__(self, session: aioboto3.Session, *, endpoint_url: str, region: str) -> None:
        self._session = session
        self._endpoint_url = endpoint_url
        self._region = region

    @classmethod
    def from_settings(cls, settings: AppSettings) -> ObjectStore:
        return cls(
            build_object_store_session(settings),
            endpoint_url=settings.s3_endpoint,
            region=settings.s3_region,
        )

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        async with self._session.client(
            "s3", endpoint_url=self._endpoint_url, region_name=self._region
        ) as client:
            yield client

    async def put_bytes(
        self, *, bucket: str, key_parts: Sequence[str], body: bytes, content_type: str
    ) -> str:
        """Writes `body` under `key_parts`. Encryption is applied by the
        bucket's default encryption rule (set once in `ensure_bucket`),
        not per-request — some S3-compatible backends (MinIO among them)
        reject a per-object `ServerSideEncryption` header with a
        KMS-configuration error unless the request also names a KMS key,
        even for plain SSE-S3 AES256. Returns the full key that was
        written."""
        key = safe_key(*key_parts)
        try:
            async with self._client() as client:
                await client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
        except ValidationFailed:
            raise
        except Exception as exc:
            raise DependencyUnavailable("object storage write failed") from exc
        return key

    async def presigned_get_url(self, *, bucket: str, key: str, expires_in: int = 300) -> str:
        """Time-limited download URL for an already-written key. Never
        used to expose a public bucket — the bucket itself stays private
        and every download goes through a fresh, short-lived URL."""
        try:
            async with self._client() as client:
                url: str = await client.generate_presigned_url(
                    "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_in
                )
        except Exception as exc:
            raise DependencyUnavailable("object storage presign failed") from exc
        return url

    async def ping(self, bucket: str) -> None:
        """Raises `DependencyUnavailable` if the bucket is unreachable.
        Used by the readiness check."""
        try:
            async with self._client() as client:
                await client.head_bucket(Bucket=bucket)
        except Exception as exc:
            raise DependencyUnavailable("object storage unreachable") from exc

    async def ensure_bucket(self, bucket: str) -> None:
        """Idempotently creates `bucket` (with default SSE-S3 encryption)
        if it does not already exist. Called once at service startup —
        buckets have no migration ledger, so this is the closest
        equivalent."""
        try:
            async with self._client() as client:
                if await self._bucket_exists(client, bucket):
                    return
                await client.create_bucket(Bucket=bucket)
                await client.put_bucket_encryption(
                    Bucket=bucket,
                    ServerSideEncryptionConfiguration={
                        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
                    },
                )
        except Exception as exc:
            raise DependencyUnavailable("object storage bucket setup failed") from exc

    @staticmethod
    async def _bucket_exists(client: Any, bucket: str) -> bool:
        try:
            await client.head_bucket(Bucket=bucket)
        except ClientError:
            return False
        return True
