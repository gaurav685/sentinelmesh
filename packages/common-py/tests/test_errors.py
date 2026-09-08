from __future__ import annotations

from uuid import uuid4

from sm_common.errors import InternalError, PermissionDenied, SmError, ValidationFailed


def test_status_mapping():
    assert PermissionDenied().http_status == 403
    assert ValidationFailed().http_status == 422
    assert InternalError().http_status == 500


def test_to_response_shape():
    rid, cid = uuid4(), uuid4()
    resp = PermissionDenied("nope").to_response(request_id=rid, correlation_id=cid)
    body = resp.model_dump(mode="json")["error"]
    assert body["code"] == "permission_denied"
    assert body["message"] == "nope"
    assert body["request_id"] == str(rid)


def test_message_is_redacted():
    rid, cid = uuid4(), uuid4()
    resp = SmError("db url postgres://u:hunter2@h/db").to_response(request_id=rid, correlation_id=cid)
    assert "hunter2" not in resp.error.message


def test_default_messages_safe():
    # no internals leaked in defaults
    for exc_cls in (PermissionDenied, ValidationFailed, InternalError):
        assert "Traceback" not in exc_cls().default_message
