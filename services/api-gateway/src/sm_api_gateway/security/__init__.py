"""Authentication and authorization for the API gateway."""

from __future__ import annotations

from .cookies import CSRF_HEADER, clear_session_cookies, set_session_cookies
from .login import LoginOutcome, authenticate_local
from .principal import Principal
from .session import (
    OidcFlowState,
    OidcStateStore,
    RedisOidcStateStore,
    RedisSessionStore,
    SessionRecord,
    SessionStore,
)

__all__ = [
    "CSRF_HEADER",
    "LoginOutcome",
    "OidcFlowState",
    "OidcStateStore",
    "Principal",
    "RedisOidcStateStore",
    "RedisSessionStore",
    "SessionRecord",
    "SessionStore",
    "authenticate_local",
    "clear_session_cookies",
    "set_session_cookies",
]
