"""`sm_common.objectstore.ObjectStore` against a real MinIO (ADR-019).

The unit tests (`packages/common-py/tests/test_infra_clients.py`) cover
`safe_key` validation and construction without a connection; only real
object-storage behavior — write, presigned download, non-existent-key
handling — is proven here.
"""

from __future__ import annotations

import pytest

from sm_common.config import AppSettings
from sm_common.errors import DependencyUnavailable, ValidationFailed
from sm_common.objectstore import ObjectStore

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_put_then_presigned_get_round_trips(object_store: ObjectStore, settings: AppSettings):
    bucket = settings.s3_bucket_reports
    key = await object_store.put_bytes(
        bucket=bucket,
        key_parts=("tenant-1", "reports", "report-1.pdf"),
        body=b"%PDF-1.4 fake report body",
        content_type="application/pdf",
    )
    assert key == "tenant-1/reports/report-1.pdf"

    url = await object_store.presigned_get_url(bucket=bucket, key=key, expires_in=60)
    assert bucket in url
    assert "X-Amz-Signature" in url or "Signature" in url


@pytest.mark.asyncio
async def test_ping_succeeds_once_bucket_exists(object_store: ObjectStore, settings: AppSettings):
    await object_store.ping(settings.s3_bucket_reports)


@pytest.mark.asyncio
async def test_ping_raises_for_unknown_bucket(object_store: ObjectStore):
    with pytest.raises(DependencyUnavailable):
        await object_store.ping("sm-reports-does-not-exist")


@pytest.mark.asyncio
async def test_ensure_bucket_is_idempotent(object_store: ObjectStore, settings: AppSettings):
    await object_store.ensure_bucket(settings.s3_bucket_reports)
    await object_store.ensure_bucket(settings.s3_bucket_reports)
    await object_store.ping(settings.s3_bucket_reports)


@pytest.mark.asyncio
async def test_put_bytes_rejects_unsafe_key_before_touching_backend(object_store: ObjectStore, settings: AppSettings):
    with pytest.raises(ValidationFailed):
        await object_store.put_bytes(
            bucket=settings.s3_bucket_reports,
            key_parts=("tenant-1", "../../etc/passwd"),
            body=b"x",
            content_type="text/plain",
        )
