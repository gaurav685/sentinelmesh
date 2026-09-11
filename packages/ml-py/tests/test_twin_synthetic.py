from __future__ import annotations

import pytest

from sm_ml.scenario import build_synthetic_env
from sm_ml.scenario.env import SyntheticEntity, SyntheticEnvironment, SyntheticKind
from sm_ml.twin import attack_paths, blast_radius, twin_from_synthetic_env
from sm_ml.twin.model import AssetKind


def test_twin_covers_every_synthetic_entity_and_nothing_else() -> None:
    env = build_synthetic_env(seed=1)
    twin = twin_from_synthetic_env(env)
    assert {a.id for a in twin.assets} == env.ids()
    assert all(a.id.startswith("sim-") for a in twin.assets)


def test_twin_is_deterministic_for_the_same_seed() -> None:
    env = build_synthetic_env(seed=7)
    a = twin_from_synthetic_env(env)
    b = twin_from_synthetic_env(env)
    assert a.assets == b.assets
    assert a.relations == b.relations
    assert a.weaknesses == b.weaknesses


def test_every_relation_endpoint_is_a_twin_asset() -> None:
    env = build_synthetic_env(seed=1)
    twin = twin_from_synthetic_env(env)
    ids = {a.id for a in twin.assets}
    for r in twin.relations:
        assert r.src in ids and r.dst in ids


def test_dc_role_gets_the_highest_criticality_and_a_critical_weakness() -> None:
    env = build_synthetic_env(seed=1)
    twin = twin_from_synthetic_env(env)
    dc = next(a for a in twin.assets if "dc" in a.tags)
    assert dc.kind is AssetKind.host
    assert dc.criticality == max(a.criticality for a in twin.assets)
    dc_weaknesses = twin.weaknesses_of(dc.id)
    assert any(w.severity == "critical" for w in dc_weaknesses)


def test_blast_radius_from_the_web_tier_reaches_beyond_its_own_host() -> None:
    env = build_synthetic_env(seed=1)
    twin = twin_from_synthetic_env(env)
    web = next(a for a in twin.assets if "web" in a.tags)
    report = blast_radius(twin, seeds={web.id}, max_hops=4)
    assert report.seeds == (web.id,)
    assert len(report.reached) > 1
    assert 0.0 < report.score <= 1.0


def test_attack_paths_exist_from_web_to_db() -> None:
    env = build_synthetic_env(seed=1)
    twin = twin_from_synthetic_env(env)
    web = next(a for a in twin.assets if "web" in a.tags)
    db = next(a for a in twin.assets if "db" in a.tags)
    paths = attack_paths(twin, sources={web.id}, targets={db.id})
    assert paths
    assert paths[0].assets[0] == web.id
    assert paths[0].assets[-1] == db.id


def test_a_twin_needs_at_least_one_host_and_ip() -> None:
    env = SyntheticEnvironment(
        seed=1, entities=(SyntheticEntity(id="sim-id-alice", kind=SyntheticKind.identity, name="alice"),)
    )
    with pytest.raises(ValueError, match="at least one host"):
        twin_from_synthetic_env(env)
