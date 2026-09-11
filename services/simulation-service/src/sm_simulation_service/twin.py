"""Read the digital twin off a scenario's synthetic environment (Phase 12).

The twin is not a second, independently-maintained asset inventory — it is a
structural read of the same `SyntheticEnvironment` a scenario runs against,
built deterministically from the request's `seed`. Blast-radius analysis runs
against this model, never against a real system.
"""

from __future__ import annotations

from sm_contracts import (
    BlastRadiusRequest,
    BlastRadiusResult,
    TwinAssetOut,
    TwinRelationOut,
    TwinSnapshot,
    TwinWeaknessOut,
)
from sm_ml.scenario import build_synthetic_env
from sm_ml.twin import TwinModel, blast_radius, twin_from_synthetic_env

__all__ = ["build_blast_radius", "build_twin_snapshot"]


def _snapshot(twin: TwinModel, seed: int) -> TwinSnapshot:
    return TwinSnapshot(
        seed=seed,
        assets=[
            TwinAssetOut(
                id=a.id, kind=a.kind.value, name=a.name, criticality=a.criticality,
                tags=sorted(a.tags),
            )
            for a in twin.assets
        ],
        relations=[
            TwinRelationOut(src=r.src, dst=r.dst, kind=r.kind.value, weight=r.weight)
            for r in twin.relations
        ],
        weaknesses=[
            TwinWeaknessOut(asset_id=w.asset_id, kind=w.kind.value, severity=w.severity, detail=w.detail)
            for w in twin.weaknesses
        ],
    )


def build_twin_snapshot(seed: int) -> TwinSnapshot:
    env = build_synthetic_env(seed)
    return _snapshot(twin_from_synthetic_env(env), seed)


def build_blast_radius(req: BlastRadiusRequest) -> BlastRadiusResult:
    env = build_synthetic_env(req.seed)
    twin = twin_from_synthetic_env(env)
    report = blast_radius(
        twin, seeds=set(req.seeds), max_hops=req.max_hops, min_weight=req.min_weight
    )
    return BlastRadiusResult(
        seed=req.seed,
        seeds=list(report.seeds),
        reached=list(report.reached),
        hop_of=report.hop_of,
        critical_reached=list(report.critical_reached),
        score=report.score,
        amplifying_weaknesses=list(report.amplifying_weaknesses),
    )
