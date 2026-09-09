"""Prometheus metrics (Engineering Constitution §14; ADR-020).

A per-process registry plus the small set of metrics every service reports. No
value is ever fabricated — these are populated only by real request/consumer
activity. `render_latest()` produces the `/metrics` exposition body.
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

    def observe_http(self, method: str, path: str, status: int, duration_s: float) -> None:
        self.http_requests.labels(self._service, method, path, str(status)).inc()
        self.http_latency.labels(self._service, method, path).observe(duration_s)

    def render_latest(self) -> bytes:
        return generate_latest(self.registry)


def build_metrics(service_name: str) -> Metrics:
    return Metrics(CollectorRegistry(), service_name)
