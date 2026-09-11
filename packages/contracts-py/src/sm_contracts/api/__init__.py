"""Phase 1 API request/response contracts (docs/CONTRACTS.md §1.2)."""

from __future__ import annotations

from .agent import (
    AgentFinding,
    AgentRunRequest,
    AgentRunResult,
    ProposedActionOut,
)
from .analyst import (
    AnalystModelInfo,
    EvidenceRef,
    ExplainRequest,
    Explanation,
)
from .auth import LoginRequest, LoginResponse, LogoutResponse, MeResponse
from .graph import GraphEdge, GraphNeighborhood, GraphNode, GraphPath
from .health import DepStatus, HealthResponse, MetaResponse, ReadyResponse
from .hunt import (
    EntitySelector,
    HuntExplainRequest,
    HuntResult,
    NlHuntRequest,
    PlanResponse,
    QueryLimits,
    QueryPlan,
    SocHuntRequest,
    SocHuntResponse,
)
from .pagination import CursorPage
from .simulation import (
    Decoy,
    DecoyInteraction,
    DecoyInteractionIn,
    DecoyKind,
    NetworkBoundary,
    RegisterDecoyRequest,
    RunScenarioRequest,
    ScenarioKind,
    ScenarioRunResult,
    SimEventOut,
)
from .soc import (
    MitreHeatmap,
    MitreHeatmapCell,
    RiskSubject,
    SocSummary,
    TimelineEntry,
    TimelineResponse,
)
from .users import CreateUserRequest, GrantRoleRequest, RoleSummary, UserResponse

__all__ = [
    "AgentFinding",
    "AgentRunRequest",
    "AgentRunResult",
    "AnalystModelInfo",
    "CreateUserRequest",
    "CursorPage",
    "Decoy",
    "DecoyInteraction",
    "DecoyInteractionIn",
    "DecoyKind",
    "DepStatus",
    "EntitySelector",
    "EvidenceRef",
    "ExplainRequest",
    "Explanation",
    "GrantRoleRequest",
    "GraphEdge",
    "GraphNeighborhood",
    "GraphNode",
    "GraphPath",
    "HealthResponse",
    "HuntExplainRequest",
    "HuntResult",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "MeResponse",
    "MetaResponse",
    "MitreHeatmap",
    "MitreHeatmapCell",
    "NetworkBoundary",
    "NlHuntRequest",
    "PlanResponse",
    "ProposedActionOut",
    "QueryLimits",
    "QueryPlan",
    "ReadyResponse",
    "RegisterDecoyRequest",
    "RiskSubject",
    "RoleSummary",
    "RunScenarioRequest",
    "ScenarioKind",
    "ScenarioRunResult",
    "SimEventOut",
    "SocHuntRequest",
    "SocHuntResponse",
    "SocSummary",
    "TimelineEntry",
    "TimelineResponse",
    "UserResponse",
]
