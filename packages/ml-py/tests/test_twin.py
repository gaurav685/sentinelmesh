from __future__ import annotations

import pytest

from sm_ml.twin import (
    AssetKind,
    DefensiveControl,
    RelationKind,
    TwinAsset,
    TwinRelation,
    TwinWeakness,
    WeaknessKind,
    apply_controls,
    attack_paths,
    blast_radius,
    build_twin,
    stress_test,
)


def _twin():
    assets = [
        TwinAsset(id="ext", kind=AssetKind.external, criticality=0.0),
        TwinAsset(id="web", kind=AssetKind.service, criticality=0.4),
        TwinAsset(id="app", kind=AssetKind.service, criticality=0.6),
        TwinAsset(id="db", kind=AssetKind.data_store, criticality=1.0, name="prod-db"),
        TwinAsset(id="admin", kind=AssetKind.identity, criticality=0.9),
    ]
    relations = [
        TwinRelation(src="ext", dst="web", kind=RelationKind.connects_to, weight=1.0),
        TwinRelation(src="web", dst="app", kind=RelationKind.depends_on, weight=0.8),
        TwinRelation(src="app", dst="db", kind=RelationKind.stores, weight=0.5),
        TwinRelation(src="admin", dst="db", kind=RelationKind.grants_access, weight=0.9),
        TwinRelation(src="web", dst="admin", kind=RelationKind.authenticates_to, weight=0.2),
    ]
    weaknesses = [
        TwinWeakness(asset_id="web", kind=WeaknessKind.public_exposure, severity="high"),
        TwinWeakness(asset_id="db", kind=WeaknessKind.excessive_privilege, severity="critical"),
    ]
    return build_twin(assets, relations, weaknesses)


def test_build_twin_is_order_independent() -> None:
    a = _twin()
    # rebuild with reversed inputs -> identical frozen model
    b = build_twin(
        list(reversed(a.assets)), list(reversed(a.relations)), list(reversed(a.weaknesses))
    )
    assert a == b


@pytest.mark.parametrize(
    "assets,relations,weaknesses,msg",
    [
        ([], [], None, "at least one asset"),
        (
            [TwinAsset(id="x", kind=AssetKind.host), TwinAsset(id="x", kind=AssetKind.host)],
            [],
            None,
            "duplicate asset id",
        ),
        (
            [TwinAsset(id="x", kind=AssetKind.host)],
            [TwinRelation(src="x", dst="y", kind=RelationKind.connects_to)],
            None,
            "endpoint not an asset",
        ),
        (
            [TwinAsset(id="x", kind=AssetKind.host)],
            [],
            [TwinWeakness(asset_id="z", kind=WeaknessKind.misconfiguration)],
            "unknown asset",
        ),
    ],
)
def test_build_twin_validates(assets, relations, weaknesses, msg) -> None:
    with pytest.raises(ValueError, match=msg):
        build_twin(assets, relations, weaknesses)


def test_attack_paths_are_bounded_simple_and_ordered() -> None:
    twin = _twin()
    paths = attack_paths(twin, sources={"ext"}, targets={"db"}, max_depth=4)
    assert paths
    # every path starts at ext, ends at db, and visits no asset twice
    for p in paths:
        assert p.assets[0] == "ext" and p.assets[-1] == "db"
        assert len(set(p.assets)) == len(p.assets)
        assert p.hops <= 4
    # ordered by feasibility descending
    assert list(paths) == sorted(paths, key=lambda p: (-p.feasibility, p.assets))
    # the direct route ext->web->app->db is the most feasible
    assert paths[0].assets == ("ext", "web", "app", "db")


def test_attack_paths_respect_max_depth() -> None:
    twin = _twin()
    assert attack_paths(twin, sources={"ext"}, targets={"db"}, max_depth=2) == ()


def test_blast_radius_is_deterministic_and_scores_by_criticality() -> None:
    twin = _twin()
    r1 = blast_radius(twin, seeds={"web"}, max_hops=3)
    r2 = blast_radius(twin, seeds={"web"}, max_hops=3)
    assert r1 == r2
    assert "db" in r1.reached and "admin" in r1.reached
    assert r1.hop_of["web"] == 0 and r1.hop_of["app"] == 1
    assert "db" in r1.critical_reached  # criticality 1.0
    # score = reached criticality / total criticality
    total = sum(a.criticality for a in twin.assets)
    reached = sum(twin.asset(a).criticality for a in r1.reached)
    assert r1.score == pytest.approx(round(reached / total, 6))
    assert "db:excessive_privilege" in r1.amplifying_weaknesses


def test_blast_radius_min_weight_prunes_hard_edges() -> None:
    twin = _twin()
    # the web->admin edge has weight 0.2; require >= 0.5 and admin is unreachable from web
    r = blast_radius(twin, seeds={"web"}, max_hops=4, min_weight=0.5)
    assert "admin" not in r.reached


def test_stress_test_breaks_paths_and_names_the_best_control() -> None:
    twin = _twin()
    # blocking `stores` alone kills the primary ext->web->app->db route but the
    # ext->web->admin->db route via grants_access survives
    partial = stress_test(
        twin,
        sources={"ext"},
        targets={"db"},
        controls=[DefensiveControl(kind="block_relation_kind", target=RelationKind.stores.value)],
        max_depth=4,
    )
    assert partial.paths_before
    assert partial.paths_broken
    assert partial.residual_risk == pytest.approx(0.18)  # the admin route
    assert partial.most_valuable_control is not None

    # add the grants_access block -> nothing reaches db
    full = stress_test(
        twin,
        sources={"ext"},
        targets={"db"},
        controls=[
            DefensiveControl(kind="block_relation_kind", target=RelationKind.stores.value),
            DefensiveControl(kind="block_relation_kind", target=RelationKind.grants_access.value),
        ],
        max_depth=4,
    )
    assert not full.paths_after
    assert full.residual_risk == 0.0


def test_apply_controls_returns_a_new_model() -> None:
    twin = _twin()
    hardened = apply_controls(twin, [DefensiveControl(kind="harden_asset", target="db")])
    assert hardened is not twin
    assert twin.weaknesses_of("db")  # original untouched
    assert not hardened.weaknesses_of("db")
