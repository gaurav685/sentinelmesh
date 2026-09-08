from __future__ import annotations

import pytest

from sm_common.security import dummy_verify, hash_password, verify_password


def test_hash_verify_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    res = verify_password(h, "correct horse battery staple")
    assert res.ok
    assert res.needs_rehash is False


def test_wrong_password():
    h = hash_password("s3cret")
    assert verify_password(h, "wrong").ok is False


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        hash_password("")


def test_malformed_hash_is_false_not_raise():
    assert verify_password("not-a-hash", "x").ok is False


def test_dummy_verify_never_raises():
    dummy_verify("anything")
    dummy_verify("")


def test_two_hashes_differ_salt():
    assert hash_password("same") != hash_password("same")
