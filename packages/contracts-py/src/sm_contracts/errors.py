"""Canonical API error contract (docs/CONTRACTS.md §1.1).

Every SentinelMesh HTTP API returns errors in exactly this shape. The body never
contains stack traces, SQL, driver messages, hostnames, or secrets
(Engineering Constitution §5). In non-production environments an implementation
MAY attach a top-level `debug` object *outside* this model; production MUST NOT.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from .common import SmBaseModel

__all__ = [
    "HTTP_STATUS_BY_CODE",
    "ErrorBody",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
]


class ErrorCode(StrEnum):
    unauthenticated = "unauthenticated"
    invalid_credentials = "invalid_credentials"
    permission_denied = "permission_denied"
    tenant_forbidden = "tenant_forbidden"
    not_found = "not_found"
    validation_error = "validation_error"
    conflict = "conflict"
    rate_limited = "rate_limited"
    dependency_unavailable = "dependency_unavailable"
    degraded_result = "degraded_result"
    payload_too_large = "payload_too_large"
    unsupported_media_type = "unsupported_media_type"
    internal_error = "internal_error"


HTTP_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.unauthenticated: 401,
    ErrorCode.invalid_credentials: 401,
    ErrorCode.permission_denied: 403,
    ErrorCode.tenant_forbidden: 403,
    ErrorCode.not_found: 404,
    ErrorCode.validation_error: 422,
    ErrorCode.conflict: 409,
    ErrorCode.rate_limited: 429,
    ErrorCode.dependency_unavailable: 503,
    ErrorCode.degraded_result: 200,  # partial success; body carries markers
    ErrorCode.payload_too_large: 413,
    ErrorCode.unsupported_media_type: 415,
    ErrorCode.internal_error: 500,
}
"""Authoritative mapping from error code to HTTP status. Implementations must use
this and not invent per-endpoint status codes."""


class ErrorDetail(SmBaseModel):
    field: str = Field(description="Dotted path, e.g. 'body.email'.")
    issue: str = Field(description="Stable machine-readable issue slug.")


class ErrorBody(SmBaseModel):
    code: ErrorCode
    message: str = Field(
        min_length=1,
        max_length=500,
        description="Human-readable, safe to display, contains no internals.",
    )
    request_id: UUID
    correlation_id: UUID
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(SmBaseModel):
    error: ErrorBody
