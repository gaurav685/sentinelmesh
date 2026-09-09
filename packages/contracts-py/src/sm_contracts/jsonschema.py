"""JSON Schema export registry.

`SCHEMA_MODELS` is the explicit list of contract types that get emitted as JSON
Schema (and downstream as TypeScript). Generic models are exported at a concrete
parameterization.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .api import (
    CreateUserRequest,
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
from .errors import ErrorResponse
from .events import EventEnvelope, UserEventPayload
from .graph import GraphCommandPayload, GraphEventPayload
from .telemetry import (
    AuthEventPayload,
    CanonicalEventPayload,
    DnsQueryPayload,
    FileAccessPayload,
    NetworkFlowPayload,
    ProcessExecPayload,
)

__all__ = ["SCHEMA_MODELS", "export_all"]

# Concrete envelope parameterizations for schema generation.
UserEventEnvelope = EventEnvelope[UserEventPayload]
NetworkFlowEnvelope = EventEnvelope[NetworkFlowPayload]
AuthEventEnvelope = EventEnvelope[AuthEventPayload]
DnsQueryEnvelope = EventEnvelope[DnsQueryPayload]
ProcessExecEnvelope = EventEnvelope[ProcessExecPayload]
FileAccessEnvelope = EventEnvelope[FileAccessPayload]
CanonicalEventEnvelope = EventEnvelope[CanonicalEventPayload]
GraphCommandEnvelope = EventEnvelope[GraphCommandPayload]
GraphEventEnvelope = EventEnvelope[GraphEventPayload]

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "ErrorResponse": ErrorResponse,
    "EventEnvelope_UserEvent": UserEventEnvelope,
    "UserEventPayload": UserEventPayload,
    "EventEnvelope_NetworkFlow": NetworkFlowEnvelope,
    "EventEnvelope_AuthEvent": AuthEventEnvelope,
    "EventEnvelope_DnsQuery": DnsQueryEnvelope,
    "EventEnvelope_ProcessExec": ProcessExecEnvelope,
    "EventEnvelope_FileAccess": FileAccessEnvelope,
    "EventEnvelope_CanonicalEvent": CanonicalEventEnvelope,
    "EventEnvelope_GraphCommand": GraphCommandEnvelope,
    "GraphCommandPayload": GraphCommandPayload,
    "EventEnvelope_GraphEvent": GraphEventEnvelope,
    "GraphEventPayload": GraphEventPayload,
    "NetworkFlowPayload": NetworkFlowPayload,
    "AuthEventPayload": AuthEventPayload,
    "DnsQueryPayload": DnsQueryPayload,
    "ProcessExecPayload": ProcessExecPayload,
    "FileAccessPayload": FileAccessPayload,
    "CanonicalEventPayload": CanonicalEventPayload,
    "Tenant": Tenant,
    "User": User,
    "Role": Role,
    "Permission": Permission,
    "RolePermission": RolePermission,
    "UserRoleGrant": UserRoleGrant,
    "Sensor": Sensor,
    "AuditRecord": AuditRecord,
    "LoginRequest": LoginRequest,
    "LoginResponse": LoginResponse,
    "LogoutResponse": LogoutResponse,
    "MeResponse": MeResponse,
    "CreateUserRequest": CreateUserRequest,
    "GrantRoleRequest": GrantRoleRequest,
    "RoleSummary": RoleSummary,
    "UserResponse": UserResponse,
    "HealthResponse": HealthResponse,
    "ReadyResponse": ReadyResponse,
    "MetaResponse": MetaResponse,
}


def export_all() -> dict[str, dict[str, Any]]:
    """Return `{name: json_schema}` for every registered contract model."""
    return {
        name: model.model_json_schema(ref_template="#/definitions/{model}")
        for name, model in SCHEMA_MODELS.items()
    }
