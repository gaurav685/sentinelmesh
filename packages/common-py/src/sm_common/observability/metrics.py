"""Prometheus metrics (Engineering Constitution §14; ADR-020).

A per-process registry plus the small set of metrics every service reports. No
value is ever fabricated — these are populated only by real request/consumer
activity. `render_latest()` produces the `/metrics` exposition body.

Model-inference latency/DEGRADED, detection latency, and graph-growth rate
(ADR-020's remaining named metrics) already have real, wired, per-service
counterparts on this same shared registry (`ml-inference`'s `InferenceMetrics`,
`detection-engine`'s `DetectionMetrics`, `graph-service`'s `GraphMetrics`) —
see the inline comments below for exactly which. They are not duplicated here.

`false_positive_feedback_total` is registered (Phase 15) but has no producer
yet: no analyst-facing "mark detection as false positive" action exists in
this build (that is a SOC-workflow feature, not an observability one). The
counter reports a real, honest `0` until such an action is built, rather than
being wired to a fabricated signal.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

__all__ = ["Metrics", "build_metrics"]

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Metrics:
    def __init__(self, registry: CollectorRegistry, service_name: str) -> None:
        self.registry = registry
        self._service = service_name

        self.http_requests = Counter(
            "sm_http_requests_total",
            "HTTP requests handled",
            ("service", "method", "path", "status"),
            registry=registry,
        )
        self.http_latency = Histogram(
            "sm_http_request_duration_seconds",
            "HTTP request duration",
            ("service", "method", "path"),
            buckets=_LATENCY_BUCKETS,
            registry=registry,
        )
        self.authn_failures = Counter(
            "sm_authn_failures_total",
            "Authentication failures",
            ("service", "reason"),
            registry=registry,
        )
        self.authz_denials = Counter(
            "sm_authz_denials_total",
            "Authorization denials",
            ("service", "permission"),
            registry=registry,
        )
        self.audit_write_failures = Counter(
            "sm_audit_write_failures_total",
            "Audit records that could not be written. Any non-zero value means "
            "the audit trail has a gap and needs investigation.",
            ("service", "action"),
            registry=registry,
        )
        self.rate_limited = Counter(
            "sm_rate_limited_total",
            "Requests rejected with 429 by the rate limiter",
            ("service",),
            registry=registry,
        )
        self.rate_limiter_errors = Counter(
            "sm_rate_limiter_errors_total",
            "Rate-limit checks that failed (the limiter failed open). Non-zero "
            "means the limiter's store was unavailable.",
            ("service",),
            registry=registry,
        )
        self.dependency_up = Gauge(
            "sm_dependency_up",
            "1 if a required dependency was reachable at the last readiness check",
            ("service", "dependency"),
            registry=registry,
        )
        # ---- event bus (ADR-008; event-model.md) --------------------------
        self.consumer_records = Counter(
            "sm_consumer_records_total",
            "Kafka records handled by a consumer group",
            ("service", "group", "topic"),
            registry=registry,
        )
        self.consumer_dlq = Counter(
            "sm_consumer_dlq_total",
            "Records a consumer sent to a dead-letter topic",
            ("service", "group", "reason"),
            registry=registry,
        )
        self.consumer_retries = Counter(
            "sm_consumer_retries_total",
            "In-process handler retries before success or DLQ",
            ("service", "group"),
            registry=registry,
        )
        self.consumer_lag = Gauge(
            "sm_consumer_lag",
            "Records behind the partition high-watermark at the last poll",
            ("service", "group", "topic", "partition"),
            registry=registry,
        )
        self.producer_send_errors = Counter(
            "sm_producer_send_errors_total",
            "Producer send attempts that raised after the client's own retries",
            ("service", "topic"),
            registry=registry,
        )
        # ---- database pool (Phase 15) --------------------------------------
        self.db_pool_size = Gauge(
            "sm_db_pool_size",
            "Configured connection-pool size at the last /metrics scrape",
            ("service",),
            registry=registry,
        )
        self.db_pool_checked_out = Gauge(
            "sm_db_pool_checked_out",
            "Connections currently checked out of the pool at the last /metrics scrape",
            ("service",),
            registry=registry,
        )
        self.db_pool_overflow = Gauge(
            "sm_db_pool_overflow",
            "Connections opened beyond pool_size at the last /metrics scrape "
            "(always 0 — this platform runs max_overflow=0)",
            ("service",),
            registry=registry,
        )
        # ---- Neo4j (Phase 15) ----------------------------------------------
        self.neo4j_query_seconds = Histogram(
            "sm_neo4j_query_duration_seconds",
            "Neo4j query duration",
            ("service", "mode"),
            buckets=_LATENCY_BUCKETS,
            registry=registry,
        )
        # Graph growth rate: `graph-service`'s own `GraphMetrics.applied` (
        # `sm_graph_commands_applied_total{op,outcome}`) already counts every
        # node/relationship write by op and outcome — `rate(...{outcome="ok"})`
        # over it *is* the growth rate. Not duplicated here.
        # Model inference latency + DEGRADED: `ml-inference`'s own
        # `InferenceMetrics` (`sm_inference_duration_seconds`,
        # `sm_inference_model_loads_total{outcome=degraded,...}`) already
        # covers this on the same shared registry. Not duplicated here.
        # Detection latency: `detection-engine`'s own `DetectionMetrics`
        # (`sm_detection_handle_seconds`, `sm_detection_degraded_total`)
        # already covers this. Not duplicated here.
        # ---- analyst feedback (Phase 15) -------------------------------------
        self.false_positive_feedback = Counter(
            "sm_false_positive_feedback_total",
            "Analyst false-positive/true-positive feedback on a detection "
            "(see module docstring: no producer wired yet in this build)",
            ("service", "outcome"),
            registry=registry,
        )

    def observe_http(self, method: str, path: str, status: int, duration_s: float) -> None:
        self.http_requests.labels(self._service, method, path, str(status)).inc()
        self.http_latency.labels(self._service, method, path).observe(duration_s)

    def refresh_db_pool(self, db: object) -> None:
        """Snapshot the pool's current counters from a `Database` (or, in a
        test, whatever stands in for one). Called just before a `/metrics`
        scrape renders — a gauge, not a stream, so a stale value between
        scrapes is never presented as current. Never raises: a test double
        with no real engine/pool simply reports nothing, same as any other
        optional signal in this module."""
        engine = getattr(db, "engine", None)
        pool = getattr(engine, "pool", None)
        size = getattr(pool, "size", None)
        checked_out = getattr(pool, "checkedout", None)
        overflow = getattr(pool, "overflow", None)
        if size is not None:
            self.db_pool_size.labels(self._service).set(size())
        if checked_out is not None:
            self.db_pool_checked_out.labels(self._service).set(checked_out())
        if overflow is not None:
            self.db_pool_overflow.labels(self._service).set(overflow())

    def observe_neo4j_query(self, mode: str, duration_s: float) -> None:
        self.neo4j_query_seconds.labels(self._service, mode).observe(duration_s)

    def record_false_positive_feedback(self, outcome: str) -> None:
        self.false_positive_feedback.labels(self._service, outcome).inc()

    def render_latest(self) -> bytes:
        return generate_latest(self.registry)


def build_metrics(service_name: str) -> Metrics:
    return Metrics(CollectorRegistry(), service_name)
