"""Scenario-engine failures."""

from __future__ import annotations

__all__ = ["ScenarioError", "ScenarioIsolationError"]


class ScenarioError(Exception):
    """Base for scenario-engine failures."""


class ScenarioIsolationError(ScenarioError):
    """A scenario spec references a target that is not a synthetic-environment
    entity. The simulation is refused — it may only touch synthetic entities."""
