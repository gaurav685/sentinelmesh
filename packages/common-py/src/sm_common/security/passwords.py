"""Password hashing (Engineering Constitution §5).

Argon2id via `argon2-cffi`. Only the local-fallback login path uses this; the
primary auth path is OIDC and stores no password.

`verify_password` returns a `PasswordVerification` so the caller can persist a
transparent rehash when parameters change. `dummy_verify` lets the login handler
spend the same time for an unknown user as for a known one (no user enumeration,
no timing oracle).
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exc

__all__ = ["PasswordVerification", "dummy_verify", "hash_password", "verify_password"]

# Parameters: OWASP-aligned starting point; tune with a benchmark before production.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

# A fixed hash of a random string, used only to burn CPU for unknown users.
_DUMMY_HASH = _hasher.hash("sm-dummy-password-not-a-secret")


@dataclass(frozen=True)
class PasswordVerification:
    ok: bool
    needs_rehash: bool = False


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> PasswordVerification:
    try:
        _hasher.verify(stored_hash, password)
    except (argon2_exc.VerifyMismatchError, argon2_exc.InvalidHashError):
        return PasswordVerification(ok=False)
    except argon2_exc.VerificationError:
        return PasswordVerification(ok=False)
    return PasswordVerification(ok=True, needs_rehash=_hasher.check_needs_rehash(stored_hash))


def dummy_verify(password: str) -> None:
    """Verify against a throwaway hash so an unknown-user login costs the same as
    a known-user login. Result is discarded."""
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except argon2_exc.VerificationError:
        pass
