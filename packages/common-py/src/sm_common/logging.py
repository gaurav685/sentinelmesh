"""Structured logging (Engineering Constitution §14, §18).

`configure_logging(settings)` installs a structlog pipeline that:
- emits JSON (or a console renderer for local dev)
- injects `request_id` / `correlation_id` from the ambient context
- injects `service` and `env`
- runs every event dict through secret redaction before rendering

Never log a password, token, secret, or API key. The redaction processor is a
safety net, not permission to do so.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.typing import EventDict, WrappedLogger

from .config import AppSettings
from .context import get_correlation_id, get_request_id
from .redaction import redact

__all__ = ["configure_logging", "get_logger"]


def _add_request_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    rid = get_request_id()
    cid = get_correlation_id()
    if rid is not None:
        event_dict.setdefault("request_id", str(rid))
    if cid is not None:
        event_dict.setdefault("correlation_id", str(cid))
    return event_dict


def _redact_processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    return cast("EventDict", redact(dict(event_dict)))


def configure_logging(settings: AppSettings) -> None:
    level = getattr(logging, settings.log_level)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_request_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_processor,
    ]

    renderer: structlog.typing.Processor
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(service=settings.service_name, env=str(settings.env))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
