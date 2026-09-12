"""`SqlBenchmarkRepository` against a real PostgreSQL.

Reads rows written the same way `ml-training` really writes them —
`save_benchmark_run`'s plain `asyncpg` insert — not through the ORM, so
this proves the ORM read side (`BenchmarkExperimentRow`) actually agrees
with the raw-SQL write side on the real table shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_ml_training.benchmark.harness import BenchmarkRun
from sm_ml_training.benchmark.persist import save_benchmark_run

from sm_api_gateway.repositories.benchmark import SqlBenchmarkRepository
from sm_common.db import Database

pytestmark = pytest.mark.integration


def _run(**over: object) -> BenchmarkRun:
    base: dict[str, object] = dict(
        dataset_id="nsl-kdd",
        train_sha256="1" * 64,
        test_sha256="2" * 64,
        preprocessing_version="nsl-kdd-v1",
        n_train=100,
        n_train_benign_used_for_fit=60,
        n_test=20,
        n_test_anomalous=8,
        model_name="mad_zscore",
        params={"z_threshold": 3.5},
        seed=1337,
        metrics={"roc_auc": 0.64},
        environment={"python_version": "3.11.5"},
        generated_at=datetime.now(UTC),
    )
    base.update(over)
    return BenchmarkRun(**base)  # type: ignore[arg-type]


async def test_get_reads_back_what_persist_wrote(clean: Database) -> None:
    database = clean
    run = _run()
    dsn = database.engine.url.render_as_string(hide_password=False)
    await save_benchmark_run(dsn, run)

    async with database.session() as session:
        repo = SqlBenchmarkRepository(session)
        rows = await repo.list_recent(dataset_id="nsl-kdd")

    assert len(rows) == 1
    exp = rows[0]
    assert exp.train_sha256 == run.train_sha256
    assert exp.model_name == "mad_zscore"
    assert exp.metrics["roc_auc"] == 0.64
    assert exp.executed is True

    async with database.session() as session:
        repo = SqlBenchmarkRepository(session)
        by_id = await repo.get(exp.id)
    assert by_id is not None
    assert by_id.id == exp.id


async def test_list_recent_orders_newest_first(clean: Database) -> None:
    database = clean
    older = _run(train_sha256="3" * 64, generated_at=datetime(2026, 1, 1, tzinfo=UTC))
    newer = _run(train_sha256="4" * 64, generated_at=datetime(2026, 6, 1, tzinfo=UTC))
    dsn = database.engine.url.render_as_string(hide_password=False)
    await save_benchmark_run(dsn, older)
    await save_benchmark_run(dsn, newer)

    async with database.session() as session:
        repo = SqlBenchmarkRepository(session)
        rows = await repo.list_recent(dataset_id="nsl-kdd", limit=10)

    shas = [r.train_sha256 for r in rows if r.train_sha256 in (older.train_sha256, newer.train_sha256)]
    assert shas.index(newer.train_sha256) < shas.index(older.train_sha256)


async def test_get_returns_none_for_an_unknown_id(clean: Database) -> None:
    from uuid import uuid4

    async with clean.session() as session:
        repo = SqlBenchmarkRepository(session)
        assert await repo.get(uuid4()) is None
