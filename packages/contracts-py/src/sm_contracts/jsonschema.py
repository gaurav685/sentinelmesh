"""JSON Schema export registry.

`SCHEMA_MODELS` is the explicit list of contract types that get emitted as JSON
Schema (and downstream as TypeScript). Generic models are exported at a concrete
parameterization.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .api import (
    AgentRunRequest,
    AgentRunResult,
    BlastRadiusRequest,
    BlastRadiusResult,
    CreateUserRequest,
    CursorPage,
    Decoy,
    DecoyInteraction,
    ExplainRequest,
    Explanation,
    GrantRoleRequest,
    GraphNeighborhood,
    GraphPath,
    HealthResponse,
    HuntResult,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    MetaResponse,
    MitreHeatmap,
    Narrative,
    NarrativeBeat,
    NlHuntRequest,
    PlanResponse,
    Prediction,
    QueryPlan,
    ReadyResponse,
    RegisterDecoyRequest,
    RoleSummary,
    RunScenarioRequest,
    ScenarioRunResult,
    SocHuntRequest,
    SocHuntResponse,
    SocSummary,
    TimelineResponse,
    TwinSnapshot,
    UserResponse,
)
from .chains import AttackChainModel, AttackChainPayload, ChainStageModel
from .detection import DetectionPayload
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
from .errors import ErrorResponse
from .events import EventEnvelope, UserEventPayload
from .graph import GraphCommandPayload, GraphEventPayload
from .memory import AdversaryFingerprint, Campaign, SimilarityMatch, ThreatMemory
from .mitre import (
    AttackMatrixVersion,
    AttackTactic,
    AttackTechnique,
    TechniqueMapping,
    TechniqueMatch,
)
from .report import (
    GroundedStatement,
    Report,
    ReportAsset,
    ReportDownload,
    ReportGeneratedPayload,
    ReportTimelineEntry,
)
from .telemetry import (
    AuthEventPayload,
    CanonicalEventPayload,
    DnsQueryPayload,
    FileAccessPayload,
    NetworkFlowPayload,
    ProcessExecPayload,
)
from .threatintel import (
    EnrichmentMatch,
    ThreatActor,
    ThreatIndicator,
    TiCampaign,
    TiSource,
    TiUpdatePayload,
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
DetectionEnvelope = EventEnvelope[DetectionPayload]
TiUpdateEnvelope = EventEnvelope[TiUpdatePayload]
AttackChainEnvelope = EventEnvelope[AttackChainPayload]

DetectionPage = CursorPage[Detection]
AlertPage = CursorPage[SecurityAlert]
ChainPage = CursorPage[AttackChainModel]
ThreatScorePage = CursorPage[ThreatScore]

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
    "EventEnvelope_Detection": DetectionEnvelope,
    "DetectionPayload": DetectionPayload,
    "Detection": Detection,
    "Anomaly": Anomaly,
    "ThreatScore": ThreatScore,
    "SecurityAlert": SecurityAlert,
    "EventEnvelope_TiUpdate": TiUpdateEnvelope,
    "TiUpdatePayload": TiUpdatePayload,
    "ThreatIndicator": ThreatIndicator,
    "ThreatActor": ThreatActor,
    "TiCampaign": TiCampaign,
    "TiSource": TiSource,
    "EnrichmentMatch": EnrichmentMatch,
    "AttackTactic": AttackTactic,
    "AttackTechnique": AttackTechnique,
    "AttackMatrixVersion": AttackMatrixVersion,
    "TechniqueMapping": TechniqueMapping,
    "TechniqueMatch": TechniqueMatch,
    "EventEnvelope_AttackChain": AttackChainEnvelope,
    "AttackChainPayload": AttackChainPayload,
    "AttackChainModel": AttackChainModel,
    "ChainStageModel": ChainStageModel,
    "SocSummary": SocSummary,
    "MitreHeatmap": MitreHeatmap,
    "TimelineResponse": TimelineResponse,
    "GraphNeighborhood": GraphNeighborhood,
    "GraphPath": GraphPath,
    "ExplainRequest": ExplainRequest,
    "Explanation": Explanation,
    "AgentRunRequest": AgentRunRequest,
    "AgentRunResult": AgentRunResult,
    "QueryPlan": QueryPlan,
    "NlHuntRequest": NlHuntRequest,
    "PlanResponse": PlanResponse,
    "HuntResult": HuntResult,
    "SocHuntRequest": SocHuntRequest,
    "SocHuntResponse": SocHuntResponse,
    "RunScenarioRequest": RunScenarioRequest,
    "ScenarioRunResult": ScenarioRunResult,
    "RegisterDecoyRequest": RegisterDecoyRequest,
    "Decoy": Decoy,
    "DecoyInteraction": DecoyInteraction,
    "TwinSnapshot": TwinSnapshot,
    "BlastRadiusRequest": BlastRadiusRequest,
    "BlastRadiusResult": BlastRadiusResult,
    "ThreatMemory": ThreatMemory,
    "Campaign": Campaign,
    "AdversaryFingerprint": AdversaryFingerprint,
    "SimilarityMatch": SimilarityMatch,
    "Prediction": Prediction,
    "Report": Report,
    "ReportAsset": ReportAsset,
    "ReportDownload": ReportDownload,
    "ReportTimelineEntry": ReportTimelineEntry,
    "GroundedStatement": GroundedStatement,
    "ReportGeneratedPayload": ReportGeneratedPayload,
    "Narrative": Narrative,
    "NarrativeBeat": NarrativeBeat,
    "CursorPage_Detection": DetectionPage,
    "CursorPage_SecurityAlert": AlertPage,
    "CursorPage_AttackChain": ChainPage,
    "CursorPage_ThreatScore": ThreatScorePage,
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
        name: model.model_json_schema(ref_template="#/$defs/{model}")
        for name, model in SCHEMA_MODELS.items()
    }
