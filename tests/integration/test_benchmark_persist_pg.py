"""`save_benchmark_run` against a real PostgreSQL.

Plain `asyncpg`, not `sm_common.db.Database` — this is the one place in the
whole codebase a service opens its own connection outside the shared
SQLAlchemy engine, so it is worth proving end to end against the real
`benchmark_experiment` table (and its `CHECK (executed IS TRUE)` constraint)
rather than trusting the SQL by inspection alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_ml_training.benchmark.harness import BenchmarkRun
from sm_ml_training.benchmark.persist import save_benchmark_run
from sqlalchemy import text

from sm_common.db import Database

pytestmark = pytest.mark.integration


def _run(**over: object) -> BenchmarkRun:
    base: dict[str, object] = dict(
        dataset_id="nsl-kdd",
        train_sha256="a" * 64,
        test_sha256="b" * 64,
        preprocessing_version="nsl-kdd-v1",
        n_train=100,
        n_train_benign_used_for_fit=60,
        n_test=20,
        n_test_anomalous=8,
        model_name="mad_zscore",
        params={"z_threshold": 3.5, "n_features": 125},
        seed=1337,
        metrics={"roc_auc": 0.64, "precision": 0.58, "recall": 0.68},
        environment={"python_version": "3.11.5", "git_commit": "deadbeef"},
        generated_at=datetime.now(UTC),
    )
    base.update(over)
    return BenchmarkRun(**base)  # type: ignore[arg-type]


async def test_save_benchmark_run_round_trips(clean: Database) -> None:
    run = _run()
    plain_dsn = clean.engine.url.render_as_string(hide_password=False).replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    await save_benchmark_run(plain_dsn, run)

    async with clean.session() as session:
        result = await session.execute(
            text(
                "SELECT dataset_id, model_name, params, metrics, environment, "
                "executed, n_train, n_test_anomalous FROM benchmark_experiment "
                "WHERE train_sha256 = :sha"
            ),
            {"sha": run.train_sha256},
        )
        row = result.mappings().one()

    assert row["dataset_id"] == "nsl-kdd"
    assert row["model_name"] == "mad_zscore"
    assert row["executed"] is True
    assert row["n_train"] == 100
    assert row["n_test_anomalous"] == 8
    # asyncpg/SQLAlchemy decode a jsonb column straight to a dict.
    assert row["params"] == {"z_threshold": 3.5, "n_features": 125}
    assert row["metrics"]["roc_auc"] == 0.64
    assert row["environment"]["git_commit"] == "deadbeef"


async def test_save_benchmark_run_accepts_the_sqlalchemy_style_dsn(clean: Database) -> None:
    run = _run(train_sha256="c" * 64)
    # clean.engine.url.render_as_string gives the SQLAlchemy `postgresql+
    # asyncpg://` form -- the same shape AppSettings.pg_dsn produces, and the
    # one every other service in this codebase already passes around.
    dsn = clean.engine.url.render_as_string(hide_password=False)
    assert dsn.startswith("postgresql+asyncpg://")
    await save_benchmark_run(dsn, run)

    async with clean.session() as session:
        result = await session.execute(
            text("SELECT 1 FROM benchmark_experiment WHERE train_sha256 = :sha"),
            {"sha": run.train_sha256},
        )
        assert result.scalar_one() == 1


async def test_each_insert_gets_its_own_row(clean: Database) -> None:
    run_a = _run(train_sha256="d" * 64)
    run_b = _run(train_sha256="e" * 64)
    dsn = clean.engine.url.render_as_string(hide_password=False)
    await save_benchmark_run(dsn, run_a)
    await save_benchmark_run(dsn, run_b)

    async with clean.session() as session:
        result = await session.execute(
            text(
                "SELECT COUNT(*) FROM benchmark_experiment "
                "WHERE train_sha256 IN (:a, :b)"
            ),
            {"a": run_a.train_sha256, "b": run_b.train_sha256},
        )
        assert result.scalar_one() == 2
