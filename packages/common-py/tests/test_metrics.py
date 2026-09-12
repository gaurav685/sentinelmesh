from __future__ import annotations

from sm_common.observability import build_metrics


def test_refresh_db_pool_reads_a_real_sqlalchemy_pool() -> None:
    class _FakePool:
        def size(self) -> int:
            return 5

        def checkedout(self) -> int:
            return 2

        def overflow(self) -> int:
            return 0

    class _FakeEngine:
        pool = _FakePool()

    class _FakeDb:
        engine = _FakeEngine()

    metrics = build_metrics("api-gateway")
    metrics.refresh_db_pool(_FakeDb())
    body = metrics.render_latest().decode()
    assert 'sm_db_pool_size{service="api-gateway"} 5.0' in body
    assert 'sm_db_pool_checked_out{service="api-gateway"} 2.0' in body
    assert 'sm_db_pool_overflow{service="api-gateway"} 0.0' in body


def test_refresh_db_pool_never_raises_for_a_test_double_with_no_engine() -> None:
    metrics = build_metrics("api-gateway")
    metrics.refresh_db_pool(object())  # no .engine at all — must not raise
    # The gauge is declared (HELP/TYPE lines exist) but never got a labeled
    # sample, since there was nothing real to read.
    assert 'sm_db_pool_size{service="api-gateway"}' not in metrics.render_latest().decode()


def test_false_positive_feedback_counter_is_real_and_labeled() -> None:
    metrics = build_metrics("detection-engine")
    metrics.record_false_positive_feedback("false_positive")
    metrics.record_false_positive_feedback("true_positive")
    metrics.record_false_positive_feedback("false_positive")
    body = metrics.render_latest().decode()
    assert (
        'sm_false_positive_feedback_total{outcome="false_positive",service="detection-engine"} 2.0'
        in body
    )
    assert (
        'sm_false_positive_feedback_total{outcome="true_positive",service="detection-engine"} 1.0'
        in body
    )
