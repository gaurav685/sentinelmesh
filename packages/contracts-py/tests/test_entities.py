from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sm_contracts import (
    CreateUserRequest,
    Sensor,
    SensorStatus,
    SensorType,
    Tenant,
    TenantStatus,
    User,
    UserStatus,
)
from sm_contracts.jsonschema import export_all


def _ts():
    return datetime.now(UTC)


def test_tenant_slug_validation():
    Tenant(id=uuid4(), slug="acme-corp", name="Acme", status=TenantStatus.active,
           created_at=_ts(), updated_at=_ts())
    for bad in ("Acme", "a", "-acme", "acme-", "acme_corp", "x" * 41):
        with pytest.raises(ValidationError):
            Tenant(id=uuid4(), slug=bad, name="Acme", status=TenantStatus.active,
                   created_at=_ts(), updated_at=_ts())


def test_user_dto_has_no_security_fields():
    fields = set(User.model_fields)
    for forbidden in ("password_hash", "failed_login_count", "locked_until"):
        assert forbidden not in fields
    u = User(
        id=uuid4(), tenant_id=uuid4(), email="a@example.com", display_name="A",
        status=UserStatus.active, created_at=_ts(), updated_at=_ts(),
    )
    assert "password" not in u.model_dump_json().lower()


def test_create_user_request_rejects_tenant_id():
    # tenant-injection / mass-assignment guard
    with pytest.raises(ValidationError):
        CreateUserRequest(email="a@example.com", display_name="A", tenant_id=str(uuid4()))


def test_sensor_valid():
    s = Sensor(
        id=uuid4(), tenant_id=uuid4(), name="edge-01", type=SensorType.network,
        status=SensorStatus.active, created_at=_ts(), updated_at=_ts(),
    )
    assert s.last_seen_at is None


def test_export_all_produces_schema_for_every_model():
    schemas = export_all()
    assert "ErrorResponse" in schemas
    assert "EventEnvelope_UserEvent" in schemas
    for name, schema in schemas.items():
        assert schema.get("type") == "object" or "$ref" in schema or "allOf" in schema, name
        assert "title" in schema, name
