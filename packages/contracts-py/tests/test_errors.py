from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from sm_contracts import (
    HTTP_STATUS_BY_CODE,
    ErrorBody,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
)


def test_every_error_code_has_http_status():
    for code in ErrorCode:
        assert code in HTTP_STATUS_BY_CODE, f"missing HTTP status mapping for {code}"


def test_status_values_are_sane():
    assert HTTP_STATUS_BY_CODE[ErrorCode.unauthenticated] == 401
    assert HTTP_STATUS_BY_CODE[ErrorCode.permission_denied] == 403
    assert HTTP_STATUS_BY_CODE[ErrorCode.internal_error] == 500
    assert HTTP_STATUS_BY_CODE[ErrorCode.rate_limited] == 429


def test_error_response_shape():
    body = ErrorBody(
        code=ErrorCode.validation_error,
        message="invalid request",
        request_id=uuid4(),
        correlation_id=uuid4(),
        details=[ErrorDetail(field="body.email", issue="invalid_format")],
    )
    resp = ErrorResponse(error=body)
    j = resp.model_dump(mode="json")
    assert set(j.keys()) == {"error"}
    assert set(j["error"].keys()) == {
        "code",
        "message",
        "request_id",
        "correlation_id",
        "details",
    }


def test_message_length_bounded():
    with pytest.raises(ValidationError):
        ErrorBody(
            code=ErrorCode.internal_error,
            message="x" * 501,
            request_id=uuid4(),
            correlation_id=uuid4(),
        )


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        ErrorBody(
            code=ErrorCode.not_found,
            message="nope",
            request_id=uuid4(),
            correlation_id=uuid4(),
            stack="secret",
        )
