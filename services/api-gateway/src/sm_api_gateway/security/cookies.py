"""Session and CSRF cookie handling (security-model.md §2, §5).

- session cookie: **httpOnly**, `Secure` (configurable only so local HTTP dev
  works; production config validation forces it on), `SameSite=Lax`, `Path=/`.
  It carries an opaque id, never identity or privileges.
- CSRF cookie: deliberately **not** httpOnly so the frontend can read it and echo
  it in `X-CSRF-Token`. Double-submit: the header must equal the value stored in
  the server-side session record.
"""

from __future__ import annotations

from fastapi import Response

from sm_common.config import AppSettings

from .session import SessionRecord

__all__ = ["CSRF_HEADER", "clear_session_cookies", "set_session_cookies"]

CSRF_HEADER = "x-csrf-token"


def set_session_cookies(
    response: Response, settings: AppSettings, record: SessionRecord
) -> None:
    max_age = settings.session_absolute_seconds
    response.set_cookie(
        settings.session_cookie_name,
        record.session_id,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        record.csrf_token,
        max_age=max_age,
        httponly=False,  # the frontend must read this to echo it back
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    # Also expose it on the login response so a client can use it immediately.
    response.headers[CSRF_HEADER] = record.csrf_token


def clear_session_cookies(response: Response, settings: AppSettings) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, path="/")
