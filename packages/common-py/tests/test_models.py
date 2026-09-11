from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from sm_common.db import AuditLog, Base, User
from sm_contracts import (
    ActorType,
    AuditResult,
    PermissionCode,
    SensorStatus,
    SensorType,
    TenantStatus,
    UserStatus,
)

EXPECTED_TABLES = {
    "tenant",
    "user",
    "role",
    "permission",
    "user_role",
    "role_permission",
    "sensor",
    "audit_log",
    # detection domain (Phase 5)
    "detection",
    "anomaly",
    "threat_score",
    "security_alert",
    # threat intel + MITRE (Phase 6)
    "attack_tactic",
    "attack_technique",
    "attack_matrix_version",
    "technique_mapping",
    "threat_indicator",
    "threat_actor",
    "ti_campaign",
    "ti_source",
    # attack-chain correlation (Phase 7)
    "attack_chain",
    "attack_chain_stage",
    # threat-hunting history (Phase 11)
    "hunt_query",
    # simulation + deception (Phase 12)
    "decoy",
    "decoy_interaction",
    # threat memory (Phase 13)
    "threat_memory",
    "campaign",
    "adversary_fingerprint",
    # reporting + attack storytelling (Phase 14)
    "report",
    "report_template",
    "narrative",
}


def _checks(table_name: str) -> dict[str, str]:
    table = Base.metadata.tables[table_name]
    return {
        c.name: str(c.sqltext)
        for c in table.constraints
        if isinstance(c, CheckConstraint) and c.name
    }


def _uniques(table_name: str) -> dict[str, tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        c.name: tuple(col.name for col in c.columns)
        for c in table.constraints
        if isinstance(c, UniqueConstraint) and c.name
    }


def test_exactly_the_expected_tables():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_tenant_scoped_table_has_tenant_id():
    for name in ("user", "sensor"):
        assert "tenant_id" in Base.metadata.tables[name].columns
        assert Base.metadata.tables[name].columns["tenant_id"].nullable is False
    # role and audit_log are nullable on purpose (system role / platform event)
    for name in ("role", "audit_log"):
        assert Base.metadata.tables[name].columns["tenant_id"].nullable is True


def test_naming_convention_applied():
    tenant = Base.metadata.tables["tenant"]
    assert tenant.primary_key.name == "pk_tenant"
    assert "uq_tenant_slug" in _uniques("tenant")


def test_user_uniqueness_and_checks():
    uq = _uniques("user")
    assert uq["uq_user_tenant_id_email"] == ("tenant_id", "email")
    assert uq["uq_user_tenant_id_external_subject"] == ("tenant_id", "external_subject")
    checks = _checks("user")
    assert "email = lower(email)" in checks["ck_user_user_email_lowercase"]
    assert "failed_login_count >= 0" in checks["ck_user_user_failed_login_count_nonneg"]


def test_user_model_holds_security_state():
    cols = set(User.__table__.columns.keys())
    for col in ("password_hash", "failed_login_count", "locked_until"):
        assert col in cols


def test_role_has_two_partial_unique_indexes():
    idx = {i.name: i for i in Base.metadata.tables["role"].indexes}
    assert idx["uq_role_system_name"].unique is True
    assert idx["uq_role_tenant_id_name"].unique is True
    assert idx["uq_role_system_name"].dialect_options["postgresql"]["where"] is not None
    assert idx["uq_role_tenant_id_name"].dialect_options["postgresql"]["where"] is not None


def test_audit_log_shape():
    assert "metadata" in AuditLog.__table__.columns  # attribute is `meta`
    assert AuditLog.meta.property.columns[0].name == "metadata"
    assert "uq_audit_log_hash" in _uniques("audit_log")
    checks = _checks("audit_log")
    assert "[0-9a-f]{64}" in checks["ck_audit_log_audit_log_hash_format"]
    assert "[0-9a-f]{64}" in checks["ck_audit_log_audit_log_prev_hash_format"]
    # created_at is application-set (input to the hash chain), not server-defaulted
    assert AuditLog.__table__.columns["created_at"].server_default is None


def test_enum_checks_cover_contract_values():
    """Guard against schema/contract drift: every enum member must appear in the
    matching CHECK constraint."""
    cases = [
        ("tenant", "ck_tenant_tenant_status", TenantStatus),
        ("user", "ck_user_user_status", UserStatus),
        ("sensor", "ck_sensor_sensor_type", SensorType),
        ("sensor", "ck_sensor_sensor_status", SensorStatus),
        ("audit_log", "ck_audit_log_audit_log_actor_type", ActorType),
        ("audit_log", "ck_audit_log_audit_log_result", AuditResult),
        ("permission", "ck_permission_permission_code", PermissionCode),
    ]
    for table, check_name, enum_cls in cases:
        sqltext = _checks(table)[check_name]
        for member in enum_cls:
            assert f"'{member.value}'" in sqltext, f"{table}.{check_name} missing {member.value}"
