"""Canonical exception handling (Engineering Constitution §5, §8, §17).

Every error leaves the API as `sm_contracts.ErrorResponse` with the correct HTTP
status. No stack trace, SQL, driver text, or secret is ever in the body. The full
detail is logged (with `request_id`) so operators can correlate.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sm_contracts import ErrorCode, ErrorDetail

from ..context import get_correlation_id, get_request_id
from ..errors import InternalError, NotFound, SmError, ValidationFailed

__all__ = ["install_exception_handlers"]

_log = structlog.get_logger("sm.errors")

_STATUS_TO_CODE: dict[int, ErrorCode] = {
    401: ErrorCode.unauthenticated,
    403: ErrorCode.permission_denied,
    404: ErrorCode.not_found,
    409: ErrorCode.conflict,
    413: ErrorCode.payload_too_large,
    415: ErrorCode.unsupported_media_type,
    429: ErrorCode.rate_limited,
}


def _ids() -> tuple[UUID, UUID]:
    return (get_request_id() or uuid4(), get_correlation_id() or uuid4())


def _json(err: SmError) -> JSONResponse:
    request_id, correlation_id = _ids()
    body = err.to_response(request_id=request_id, correlation_id=correlation_id)
    return JSONResponse(status_code=err.http_status, content=body.model_dump(mode="json"))


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SmError)
    async def _handle_sm_error(_: Request, exc: SmError) -> JSONResponse:
        if exc.http_status >= 500:
            _log.error("unhandled_sm_error", error_type=type(exc).__name__, message=exc.message)
        else:
            _log.info("sm_error", code=str(exc.code), message=exc.message)
        return _json(exc)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(field=".".join(str(p) for p in e.get("loc", [])), issue=e.get("type", "invalid"))
            for e in exc.errors()
        ]
        return _json(ValidationFailed(details=details))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.internal_error)
        mapped = SmError(str(exc.detail) if exc.detail else None)
        mapped.code = code
        if code is ErrorCode.internal_error:
            _log.error("http_exception", status=exc.status_code, detail=str(exc.detail))
            return _json(InternalError())
        return _json(mapped)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        request_id, _cid = _ids()
        _log.exception("unhandled_exception", error_type=type(exc).__name__, request_id=str(request_id))
        return _json(InternalError())

    # keep a typed reference so linters do not flag the closures as unused
    _ = (_handle_sm_error, _handle_validation, _handle_http, _handle_unexpected, NotFound)
