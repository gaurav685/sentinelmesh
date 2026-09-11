"""The synthetic telemetry a scenario produces.

Every `SimEvent` is marked `simulated=True` and carries its `scenario_id`. These
are fed into the normal pipeline (normalization -> detection -> correlation ->
graph) so a simulation exercises real detections, but every consumer can see it
is a drill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = ["SimEvent", "SimEventKind"]


class SimEventKind(StrEnum):
    auth_failed = "auth_failed"
    auth_success = "auth_success"
    process_exec = "process_exec"
    file_access = "file_access"
    network_flow = "network_flow"


@dataclass(frozen=True)
class SimEvent:
    step: int
    #: Seconds after the scenario start.
    at_offset_s: int
    kind: SimEventKind
    actor: str
    target: str
    attributes: dict[str, str] = field(default_factory=dict)
    simulated: bool = True
    scenario_id: str = ""
