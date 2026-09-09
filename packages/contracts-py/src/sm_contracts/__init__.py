"""SentinelMesh canonical contracts.

Single source of truth for the event envelope, the API error contract, and the
Phase-1 entity / API schemas. TypeScript types for the frontend are generated
from the JSON Schema this package emits (`scripts/gen_contracts.py`).

Import surface is intentionally flat for consumers:

    from sm_contracts import EventEnvelope, ErrorResponse, User
"""

from __future__ import annotations

from .api import (
    CreateUserRequest,
    CursorPage,
    DepStatus,
    GrantRoleRequest,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    MetaResponse,
    ReadyResponse,
    RoleSummary,
    UserResponse,
)
from .common import SmBaseModel, TenantScoped, TimestampedModel, to_utc
from .entities import (
    AuditRecord,
    Permission,
    Role,
    RolePermission,
    Sensor,
    Tenant,
    User,
    UserRoleGrant,
)
from .enums import (
    ActorType,
    AuditResult,
    PermissionCode,
    SensorStatus,
    SensorType,
    SystemRole,
    TenantStatus,
    UserStatus,
)
from .errors import (
    HTTP_STATUS_BY_CODE,
    ErrorBody,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
)
from .events import (
    EVENT_PAYLOAD_REGISTRY,
    EventEnvelope,
    EventSource,
    EventType,
    SourceType,
    UserEventAction,
    UserEventPayload,
)
from .telemetry import (
    TELEMETRY_PAYLOADS,
    AuthEventPayload,
    AuthOutcome,
    CanonicalEventPayload,
    CanonicalKind,
    Direction,
    DnsQueryPayload,
    EntityKind,
    EntityRef,
    FileAccessPayload,
    FileAction,
    NetworkFlowPayload,
    ProcessExecPayload,
)
from .version import CONTRACTS_VERSION, ENVELOPE_SCHEMA_VERSION

__all__ = [  # noqa: RUF022  (grouped by domain for readability, not alphabetically)
    "CONTRACTS_VERSION",
    "ENVELOPE_SCHEMA_VERSION",
    # base
    "SmBaseModel",
    "TimestampedModel",
    "TenantScoped",
    "to_utc",
    # errors
    "ErrorCode",
    "ErrorDetail",
    "ErrorBody",
    "ErrorResponse",
    "HTTP_STATUS_BY_CODE",
    # events
    "EventEnvelope",
    "EventType",
    "SourceType",
    "EventSource",
    "UserEventAction",
    "UserEventPayload",
    "EVENT_PAYLOAD_REGISTRY",
    # telemetry payloads (Phase 2)
    "NetworkFlowPayload",
    "AuthEventPayload",
    "DnsQueryPayload",
    "ProcessExecPayload",
    "FileAccessPayload",
    "CanonicalEventPayload",
    "EntityRef",
    "EntityKind",
    "CanonicalKind",
    "Direction",
    "AuthOutcome",
    "FileAction",
    "TELEMETRY_PAYLOADS",
    # enums
    "TenantStatus",
    "UserStatus",
    "SystemRole",
    "PermissionCode",
    "ActorType",
    "AuditResult",
    "SensorType",
    "SensorStatus",
    # entities
    "Tenant",
    "User",
    "Role",
    "Permission",
    "RolePermission",
    "UserRoleGrant",
    "Sensor",
    "AuditRecord",
    # api
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "MeResponse",
    "CreateUserRequest",
    "GrantRoleRequest",
    "RoleSummary",
    "UserResponse",
    "CursorPage",
    "HealthResponse",
    "ReadyResponse",
    "MetaResponse",
    "DepStatus",
]
