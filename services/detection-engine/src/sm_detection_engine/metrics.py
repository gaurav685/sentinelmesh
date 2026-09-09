"""detection-engine Prometheus metrics (shared registry).

Retry / DLQ / lag are the shared bus metrics — not duplicated here.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from sm_common.observability import Metrics

__all__ = ["DetectionMetrics"]


class DetectionMetrics:
    def __init__(self, base: Metrics, service_name: str) -> None:
        self._s = service_name
        reg = base.registry
        self.events = Counter(
            "sm_detection_events_total", "canonical events consumed",
            ("service", "kind"), registry=reg,
        )
        self.anomalies = Counter(
            "sm_detection_anomalies_total", "anomalies scored, by method and verdict",
            ("service", "method", "verdict"), registry=reg,
        )
        self.detections = Counter(
            "sm_detection_detections_total", "detections written, by detector and severity",
            ("service", "detector", "severity"), registry=reg,
        )
        self.alerts = Counter(
            "sm_detection_alerts_total", "alert outcomes",
            ("service", "outcome"), registry=reg,
        )
        self.degraded = Counter(
            "sm_detection_degraded_total", "scoring degraded, by reason",
            ("service", "reason"), registry=reg,
        )
        self.rule_hits = Counter(
            "sm_detection_rule_hits_total", "rule matches by rule id",
            ("service", "rule_id"), registry=reg,
        )
        self.alert_failures = Counter(
            "sm_detection_alert_failures_total", "alert generation failures",
            ("service",), registry=reg,
        )
        self.duration = Histogram(
            "sm_detection_handle_seconds", "wall time to process one canonical event",
            ("service",), registry=reg,
        )

    def event(self, kind: str) -> None:
        self.events.labels(self._s, kind).inc()

    def anomaly(self, method: str, is_anomaly: bool) -> None:
        self.anomalies.labels(self._s, method, "anomaly" if is_anomaly else "normal").inc()

    def detection(self, detector: str, severity: str) -> None:
        self.detections.labels(self._s, detector, severity).inc()

    def alert(self, outcome: str) -> None:
        self.alerts.labels(self._s, outcome).inc()

    def degrade(self, reason: str) -> None:
        self.degraded.labels(self._s, reason).inc()

    def rule_hit(self, rule_id: str) -> None:
        self.rule_hits.labels(self._s, rule_id).inc()

    def alert_failure(self) -> None:
        self.alert_failures.labels(self._s).inc()
