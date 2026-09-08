from __future__ import annotations

from sm_common.redaction import REDACTED, looks_sensitive, redact


def test_sensitive_keys():
    for k in ("password", "PG_PASSWORD", "api_key", "authorization", "signing_key", "session_token"):
        assert looks_sensitive(k)
    for k in ("host", "port", "email", "display_name"):
        assert not looks_sensitive(k)


def test_dict_key_redaction_recursive():
    data = {"user": "a@b.com", "pg_password": "hunter2", "nested": {"api_key": "xyz", "ok": 1}}
    red = redact(data)
    assert red["pg_password"] == REDACTED
    assert red["nested"]["api_key"] == REDACTED
    assert red["nested"]["ok"] == 1
    assert red["user"] == "a@b.com"


def test_text_patterns():
    assert "hunter2" not in redact("connect postgres://u:hunter2@db:5432/x")
    assert REDACTED in redact("Authorization: Bearer abc.def.ghi")
    jwt = "eyJhbGciOi.eyJzdWIiOi.sig-part"
    assert jwt not in redact(f"token={jwt}")


def test_non_string_scalars_unchanged():
    assert redact(42) == 42
    assert redact(None) is None
    assert redact([1, {"secret": "s"}])[1]["secret"] == REDACTED
