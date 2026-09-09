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
from .detection import (
    DETECTION_PAYLOADS,
    DetectionPayload,
    EvidenceItem,
    EvidenceKind,
    detection_dedup_key,
    detection_id_for,
)
from .entities import (
    Anomaly,
    AuditRecord,
    Detection,
    Permission,
    Role,
    RolePermission,
    SecurityAlert,
    Sensor,
    Tenant,
    ThreatScore,
    User,
    UserRoleGrant,
)
from .enums import (
    ActorType,
    AlertStatus,
    AnomalyMethod,
    AuditResult,
    DetectionStatus,
    DetectorKind,
    PermissionCode,
    ScoringStatus,
    SensorStatus,
    SensorType,
    Severity,
    SystemRole,
    TenantStatus,
    ThreatSubjectType,
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
    make_partition_key,
)
from .graph import (
    GRAPH_NODE_KEY,
    GRAPH_NODE_LABELS,
    GRAPH_PAYLOADS,
    GRAPH_REL_TYPES,
    GraphCommandPayload,
    GraphEndpoint,
    GraphEventPayload,
    GraphMutationOutcome,
    GraphOp,
    graph_command_id,
    graph_node_uid,
    normalize_label,
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
from .topics import (
    EVENT_TYPE_TOPIC,
    EVENT_TYPE_VERSION,
    TOPICS,
    TopicSpec,
    dlq_topic,
    replay_group,
    topic_for_event_type,
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
    "make_partition_key",
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
    # topics (Phase 3)
    "TOPICS",
    "TopicSpec",
    "EVENT_TYPE_TOPIC",
    "EVENT_TYPE_VERSION",
    "topic_for_event_type",
    "dlq_topic",
    "replay_group",
    # graph commands (Phase 3) + graph model allowlist + graph events (Phase 4)
    "GraphCommandPayload",
    "GraphEndpoint",
    "GraphEventPayload",
    "GraphMutationOutcome",
    "GraphOp",
    "GRAPH_PAYLOADS",
    "graph_command_id",
    "graph_node_uid",
    "GRAPH_NODE_LABELS",
    "GRAPH_NODE_KEY",
    "GRAPH_REL_TYPES",
    "normalize_label",
    # detection + anomaly (Phase 5)
    "DetectionPayload",
    "DETECTION_PAYLOADS",
    "EvidenceItem",
    "EvidenceKind",
    "detection_dedup_key",
    "detection_id_for",
    "Severity",
    "DetectorKind",
    "AnomalyMethod",
    "ScoringStatus",
    "DetectionStatus",
    "AlertStatus",
    "ThreatSubjectType",
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
    "Detection",
    "Anomaly",
    "ThreatScore",
    "SecurityAlert",
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
