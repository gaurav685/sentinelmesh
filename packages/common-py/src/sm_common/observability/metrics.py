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
        self.dependency_up = Gauge(
            "sm_dependency_up",
            "1 if a required dependency was reachable at the last readiness check",
            ("service", "dependency"),
            registry=registry,
        )

    def observe_http(self, method: str, path: str, status: int, duration_s: float) -> None:
        self.http_requests.labels(self._service, method, path, str(status)).inc()
        self.http_latency.labels(self._service, method, path).observe(duration_s)

    def render_latest(self) -> bytes:
        return generate_latest(self.registry)


def build_metrics(service_name: str) -> Metrics:
    return Metrics(CollectorRegistry(), service_name)
