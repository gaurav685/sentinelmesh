"""Per-request ambient context.

`request_id` and `correlation_id` are stored in `contextvars` so any code (logging
processor, error handler, repository, event producer) can read them without
threading them through every call. Set by the FastAPI request middleware; also
settable directly for workers/consumers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

__all__ = [
    "get_correlation_id",
    "get_request_id",
    "request_context",
    "set_request_context",
]

_request_id: ContextVar[UUID | None] = ContextVar("sm_request_id", default=None)
_correlation_id: ContextVar[UUID | None] = ContextVar("sm_correlation_id", default=None)


def get_request_id() -> UUID | None:
    return _request_id.get()


def get_correlation_id() -> UUID | None:
    return _correlation_id.get()


def set_request_context(request_id: UUID, correlation_id: UUID) -> tuple[object, object]:
    """Set both ids; returns the reset tokens (call `reset_request_context`)."""
    return _request_id.set(request_id), _correlation_id.set(correlation_id)


def reset_request_context(tokens: tuple[object, object]) -> None:
    rid_token, cid_token = tokens
    _request_id.reset(rid_token)  # type: ignore[arg-type]
    _correlation_id.reset(cid_token)  # type: ignore[arg-type]


@contextmanager
def request_context(request_id: UUID, correlation_id: UUID) -> Iterator[None]:
    tokens = set_request_context(request_id, correlation_id)
    try:
        yield
    finally:
        reset_request_context(tokens)
