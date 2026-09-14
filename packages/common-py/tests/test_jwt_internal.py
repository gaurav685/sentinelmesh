from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest

from sm_common.errors import Unauthenticated
from sm_common.security import mint_internal_token, verify_internal_token

KEY = "signing-key-abcdefghijklmnopqrstuvwxyz"
TENANT = uuid4()


def test_roundtrip():
    tok = mint_internal_token(
        signing_key=KEY, subject="user-1", tenant_id=TENANT, audience="graph-service",
        roles=("analyst",), permissions=("hunt:query",),
    )
    p = verify_internal_token(tok, signing_keys=[KEY], audience="graph-service")
    assert p.subject == "user-1"
    assert p.tenant_id == TENANT
    assert p.roles == ("analyst",)
    assert p.permissions == ("hunt:query",)
    assert p.jti


def test_wrong_audience_rejected():
    tok = mint_internal_token(signing_key=KEY, subject="u", tenant_id=TENANT, audience="a")
    with pytest.raises(Unauthenticated):
        verify_internal_token(tok, signing_keys=[KEY], audience="b")


def test_wrong_key_rejected():
    tok = mint_internal_token(signing_key=KEY, subject="u", tenant_id=TENANT, audience="a")
    with pytest.raises(Unauthenticated):
        verify_internal_token(tok, signing_keys=["a-different-key-also-32-bytes-ok!"], audience="a")


def test_key_rotation_accepts_old_key():
    tok = mint_internal_token(signing_key=KEY, subject="u", tenant_id=TENANT, audience="a")
    p = verify_internal_token(tok, signing_keys=["another-signing-key-32-bytes-long!", KEY], audience="a")
    assert p.subject == "u"


def test_expired_rejected():
    tok = mint_internal_token(
        signing_key=KEY, subject="u", tenant_id=TENANT, audience="a", ttl_seconds=30
    )
    time.sleep(0)
    # forge an expired token with the same key to avoid a 30s sleep
    expired = jwt.encode(
        {"iss": "sentinelmesh-internal", "sub": "u", "aud": "a", "tenant_id": str(TENANT),
         "iat": int(time.time()) - 100, "exp": int(time.time()) - 10},
        KEY, algorithm="HS256",
    )
    with pytest.raises(Unauthenticated):
        verify_internal_token(expired, signing_keys=[KEY], audience="a", leeway_seconds=0)
    # sanity: fresh token still ok
    assert verify_internal_token(tok, signing_keys=[KEY], audience="a").subject == "u"


def test_empty_signing_key_rejected():
    with pytest.raises(ValueError):
        mint_internal_token(signing_key="", subject="u", tenant_id=TENANT, audience="a")


def test_empty_audience_rejected():
    with pytest.raises(ValueError, match="audience must not be empty"):
        mint_internal_token(signing_key=KEY, subject="u", tenant_id=TENANT, audience="")
    tok = mint_internal_token(signing_key=KEY, subject="u", tenant_id=TENANT, audience="a")
    with pytest.raises(ValueError, match="audience must not be empty"):
        verify_internal_token(tok, signing_keys=[KEY], audience="")


def test_empty_signing_keys_rejected():
    tok = mint_internal_token(signing_key=KEY, subject="u", tenant_id=TENANT, audience="a")
    with pytest.raises(ValueError, match="signing_keys must not be empty"):
        verify_internal_token(tok, signing_keys=[], audience="a")
