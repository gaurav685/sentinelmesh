"""Enumerations shared across SentinelMesh contracts.

String-valued so they serialize stably in JSON, events, and the database.
Adding a member is backward-compatible; removing or renaming one is a breaking
change and requires a `CONTRACTS_VERSION` bump.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ActorType",
    "AlertStatus",
    "AnomalyMethod",
    "AuditResult",
    "DetectionStatus",
    "DetectorKind",
    "PermissionCode",
    "ScoringStatus",
    "SensorStatus",
    "SensorType",
    "Severity",
    "SystemRole",
    "TenantStatus",
    "ThreatSubjectType",
    "UserStatus",
]


class TenantStatus(StrEnum):
    active = "active"
    suspended = "suspended"


class UserStatus(StrEnum):
    active = "active"
    disabled = "disabled"
    invited = "invited"


class SystemRole(StrEnum):
    """Built-in roles seeded at migration time (Phase 1)."""

    platform_operator = "platform_operator"
    tenant_admin = "tenant_admin"
    lead = "lead"
    analyst = "analyst"
    read_only = "read_only"


class PermissionCode(StrEnum):
    """Deny-by-default: absence of a code means the action is forbidden.

    Phase 1 seeds the auth/admin subset. Later phases add their own codes; this
    enum grows additively.
    """

    # identity / administration
    users_read = "users:read"
    users_create = "users:create"
    users_update = "users:update"
    roles_read = "roles:read"
    roles_grant = "roles:grant"
    sensors_read = "sensors:read"
    sensors_manage = "sensors:manage"
    audit_read = "audit:read"
    ops_read = "ops:read"

    # placeholders referenced by later-phase contracts (traceability), not yet enforced
    detections_read = "detections:read"
    hunt_query = "hunt:query"
    reports_generate = "reports:generate"
    response_execute = "response:execute"
    response_approve = "response:approve"


class ActorType(StrEnum):
    user = "user"
    sensor = "sensor"
    service = "service"
    agent = "agent"
    system = "system"


class AuditResult(StrEnum):
    allow = "allow"
    deny = "deny"
    success = "success"
    failure = "failure"


class SensorType(StrEnum):
    network = "network"
    auth = "auth"
    dns = "dns"
    process = "process"
    file = "file"
    mixed = "mixed"


class SensorStatus(StrEnum):
    active = "active"
    disabled = "disabled"
    pending = "pending"


# --------------------------------------------------------------------------- #
# detection + anomaly (Phase 5)
# --------------------------------------------------------------------------- #
class Severity(StrEnum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class DetectorKind(StrEnum):
    """How a detection was produced."""

    rule = "rule"                     # deterministic rule match
    statistical = "statistical"      # rolling-quantile / MAD anomaly, no trained model
    isolation_forest = "isolation_forest"
    autoencoder = "autoencoder"
    composite = "composite"          # combined deterministic score over several inputs


class AnomalyMethod(StrEnum):
    mad_zscore = "mad_zscore"
    rolling_quantile = "rolling_quantile"
    isolation_forest = "isolation_forest"
    autoencoder = "autoencoder"


class ScoringStatus(StrEnum):
    """ADR-013: a model timeout / outage degrades the score, never drops it."""

    ok = "ok"
    degraded = "degraded"


class DetectionStatus(StrEnum):
    """Detection lifecycle (Constitution §17)."""

    new = "new"
    triaged = "triaged"
    confirmed = "confirmed"
    dismissed = "dismissed"
    suppressed = "suppressed"


class AlertStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    closed = "closed"


class ThreatSubjectType(StrEnum):
    identity = "identity"
    host = "host"
    ip = "ip"
    domain = "domain"
    detection = "detection"
