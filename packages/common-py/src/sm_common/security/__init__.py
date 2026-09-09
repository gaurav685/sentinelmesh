"""Security primitives: password hashing, internal service tokens, OIDC client,
sensor credential authentication."""

from __future__ import annotations

from .jwt_internal import InternalPrincipal, mint_internal_token, verify_internal_token
from .oidc import (
    OidcClient,
    OidcIdentity,
    OidcTokens,
    PkcePair,
    make_pkce,
    new_state,
)
from .passwords import PasswordVerification, dummy_verify, hash_password, verify_password
from .sensor_auth import SensorAuth, SensorIdentity

__all__ = [
    "InternalPrincipal",
    "OidcClient",
    "OidcIdentity",
    "OidcTokens",
    "PasswordVerification",
    "PkcePair",
    "SensorAuth",
    "SensorIdentity",
    "dummy_verify",
    "hash_password",
    "make_pkce",
    "mint_internal_token",
    "new_state",
    "verify_internal_token",
    "verify_password",
]
