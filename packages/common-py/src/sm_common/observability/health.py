"""Health and readiness (Engineering Constitution §14).

- liveness (`/healthz`): the process is up. No dependency checks.
- readiness (`/readyz`): every *required* dependency is reachable. If not, the
  orchestrator should stop routing traffic to this instance.

A service registers `DependencyCheck` objects; `evaluate_readiness` runs them
(bounded, concurrent) and produces the canonical `ReadyResponse`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from sm_contracts import DepStatus, HealthResponse, ReadyResponse

__all__ = [
    "DependencyCheck",
    "Pingable",
    "evaluate_readiness",
    "liveness",
    "probe_check",
]

CheckFn = Callable[[], Awaitable[None]]


class DependencyCheck:
    """Wraps an async probe. The probe raises on failure; a clean return is healthy."""

    def __init__(
        self, name: str, probe: CheckFn, *, required: bool = True, timeout_s: float = 3.0
    ) -> None:
        self.name = name
        self._probe = probe
        self.required = required
        self.timeout_s = timeout_s

    async def run(self) -> tuple[DepStatus, bool]:
        start = time.perf_counter()
        try:
            await asyncio.wait_for(self._probe(), timeout=self.timeout_s)
            latency = (time.perf_counter() - start) * 1000
            return (
                DepStatus(name=self.name, healthy=True, latency_ms=round(latency, 2)),
                self.required,
            )
        except TimeoutError:
            return DepStatus(name=self.name, healthy=False, detail="timeout"), self.required
        except Exception as exc:  # health probe must never raise out
            return DepStatus(name=self.name, healthy=False, detail=type(exc).__name__), self.required


class Pingable(Protocol):
    async def ping(self) -> None: ...


def probe_check(
    name: str, obj: Pingable, *, required: bool = True, timeout_s: float = 3.0
) -> DependencyCheck:
    """Build a `DependencyCheck` from any object exposing an async `ping()`
    (e.g. `Database`, `Cache`)."""
    return DependencyCheck(name, obj.ping, required=required, timeout_s=timeout_s)


def liveness(service_name: str, version: str) -> HealthResponse:
    return HealthResponse(service=service_name, version=version)


async def evaluate_readiness(checks: list[DependencyCheck]) -> ReadyResponse:
    if not checks:
        return ReadyResponse(ready=True, dependencies=[])
    results = await asyncio.gather(*(c.run() for c in checks))
    statuses = [s for s, _ in results]
    ready = all(s.healthy for s, required in results if required)
    return ReadyResponse(ready=ready, dependencies=statuses)
