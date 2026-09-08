"""Application error hierarchy.

Raise an `SmError` subclass anywhere; the FastAPI exception handler
(`sm_common.fastapi.exception_handlers`) turns it into the canonical
`sm_contracts.ErrorResponse` with the right HTTP status. The message must be safe
to show a caller — no internals, no secrets (Engineering Constitution §5, §8).
"""

from __future__ import annotations

from uuid import UUID

from sm_contracts import (
    HTTP_STATUS_BY_CODE,
    ErrorBody,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
)

from .redaction import redact

__all__ = [
    "Conflict",
    "DependencyUnavailable",
    "InternalError",
    "InvalidCredentials",
    "NotFound",
    "PayloadTooLarge",
    "PermissionDenied",
    "RateLimited",
    "SmError",
    "TenantForbidden",
    "Unauthenticated",
    "UnsupportedMediaType",
    "ValidationFailed",
]


class SmError(Exception):
    """Base application error. `code` selects the HTTP status via
    `HTTP_STATUS_BY_CODE`."""

    code: ErrorCode = ErrorCode.internal_error
    default_message: str = "internal error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or []
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return HTTP_STATUS_BY_CODE[self.code]

    def to_response(self, *, request_id: UUID, correlation_id: UUID) -> ErrorResponse:
        safe_message = redact(self.message)
        return ErrorResponse(
            error=ErrorBody(
                code=self.code,
                message=safe_message,
                request_id=request_id,
                correlation_id=correlation_id,
                details=self.details,
            )
        )


class Unauthenticated(SmError):
    code = ErrorCode.unauthenticated
    default_message = "authentication required"


class InvalidCredentials(SmError):
    code = ErrorCode.invalid_credentials
    default_message = "invalid email or password"


class PermissionDenied(SmError):
    code = ErrorCode.permission_denied
    default_message = "you do not have permission to perform this action"


class TenantForbidden(SmError):
    code = ErrorCode.tenant_forbidden
    default_message = "resource does not belong to your tenant"


class NotFound(SmError):
    code = ErrorCode.not_found
    default_message = "resource not found"


class ValidationFailed(SmError):
    code = ErrorCode.validation_error
    default_message = "the request is invalid"


class Conflict(SmError):
    code = ErrorCode.conflict
    default_message = "the request conflicts with the current state"


class RateLimited(SmError):
    code = ErrorCode.rate_limited
    default_message = "too many requests"


class DependencyUnavailable(SmError):
    code = ErrorCode.dependency_unavailable
    default_message = "a required dependency is unavailable"


class PayloadTooLarge(SmError):
    code = ErrorCode.payload_too_large
    default_message = "request body too large"


class UnsupportedMediaType(SmError):
    code = ErrorCode.unsupported_media_type
    default_message = "unsupported media type"


class InternalError(SmError):
    code = ErrorCode.internal_error
    default_message = "internal error"
