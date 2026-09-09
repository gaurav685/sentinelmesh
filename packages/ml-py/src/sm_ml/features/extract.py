"""Deterministic feature extraction: `CanonicalEventPayload` -> `FeatureVector`.

Pure functions of the event — same event in, same vector out, no clock, no
randomness, no I/O. Values are clamped to the schema's declared range so a
hostile / broken event cannot push a feature to infinity.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sm_contracts import CanonicalEventPayload, CanonicalKind

from .schema import schema_for

__all__ = ["FeatureVector", "extract_features", "shannon_entropy"]


@dataclass(frozen=True)
class FeatureVector:
    kind: CanonicalKind
    schema_version: str
    values: dict[str, float]

    @property
    def names(self) -> tuple[str, ...]:
        return schema_for(self.kind).names

    @property
    def vector(self) -> list[float]:
        """Values in schema order — the input a model consumes."""
        return [self.values[name] for name in self.names]


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _ln1p(x: float) -> float:
    return math.log1p(max(0.0, x))


def _num(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _hour_trig(occurred_at: datetime) -> tuple[float, float]:
    frac = (occurred_at.hour + occurred_at.minute / 60.0) / 24.0
    angle = 2.0 * math.pi * frac
    return math.sin(angle), math.cos(angle)


def _finish(kind: CanonicalKind, raw: dict[str, float]) -> FeatureVector:
    schema = schema_for(kind)
    values = {spec.name: spec.clamp(float(raw.get(spec.name, 0.0))) for spec in schema.specs}
    return FeatureVector(kind=kind, schema_version=schema.version, values=values)


def extract_features(canonical: CanonicalEventPayload) -> FeatureVector:
    kind = canonical.kind
    attrs = canonical.attributes
    if kind is CanonicalKind.auth:
        sin, cos = _hour_trig(canonical.occurred_at)
        principal = canonical.actor.value if canonical.actor else ""
        return _finish(kind, {
            "is_failure": 1.0 if (canonical.outcome or "").lower() == "failure" else 0.0,
            "hour_sin": sin,
            "hour_cos": cos,
            "day_of_week": float(canonical.occurred_at.weekday()),
            "has_source_ip": 1.0 if attrs.get("source_ip") else 0.0,
            "principal_len": float(len(principal)),
            "principal_entropy": shannon_entropy(principal),
        })
    if kind is CanonicalKind.network_flow:
        dst_port = _num(attrs.get("dst_port"))
        return _finish(kind, {
            "bytes_sent_log": _ln1p(_num(attrs.get("bytes_sent"))),
            "bytes_received_log": _ln1p(_num(attrs.get("bytes_received"))),
            "packets_total_log": _ln1p(
                _num(attrs.get("packets_sent")) + _num(attrs.get("packets_received"))
            ),
            "dst_port": dst_port,
            "dst_port_is_system": 1.0 if 0 < dst_port < 1024 else 0.0,
            "dst_port_is_ephemeral": 1.0 if dst_port >= 49152 else 0.0,
            "proto_tcp": 1.0 if str(attrs.get("protocol", "")).lower() == "tcp" else 0.0,
            "direction_outbound": 1.0 if str(attrs.get("direction", "")).lower() == "outbound" else 0.0,
        })
    if kind is CanonicalKind.dns:
        qname = canonical.target.value if canonical.target else ""
        labels = [x for x in qname.split(".") if x]
        answers = attrs.get("answers")
        answer_count = len(answers) if isinstance(answers, list) else 0
        return _finish(kind, {
            "qname_len": float(len(qname)),
            "qname_entropy": shannon_entropy(qname),
            "label_count": float(len(labels)),
            "longest_label_len": float(max((len(x) for x in labels), default=0)),
            "is_nxdomain": 1.0 if str(attrs.get("response_code", "")).upper() == "NXDOMAIN" else 0.0,
            "answer_count": float(answer_count),
            "qtype_is_txt": 1.0 if str(attrs.get("query_type", "")).upper() == "TXT" else 0.0,
        })
    if kind is CanonicalKind.process_exec:
        cmdline = str(attrs.get("command_line", "") or "")
        name = canonical.target.value if canonical.target else ""
        path = str(attrs.get("process_path", "") or "")
        return _finish(kind, {
            "cmdline_len": float(len(cmdline)),
            "cmdline_entropy": shannon_entropy(cmdline),
            "name_entropy": shannon_entropy(name),
            "is_signed": 1.0 if attrs.get("signed") is True else 0.0,
            "has_parent": 1.0 if attrs.get("parent_process_name") else 0.0,
            "path_depth": float(path.count("/") + path.count("\\")),
        })
    if kind is CanonicalKind.file_access:
        action = (canonical.action or "").lower()
        path = canonical.target.value if canonical.target else ""
        return _finish(kind, {
            "is_write": 1.0 if action in {"write", "create"} else 0.0,
            "is_delete": 1.0 if action == "delete" else 0.0,
            "is_permission_change": 1.0 if action == "permission_change" else 0.0,
            "path_len": float(len(path)),
            "path_depth": float(path.count("/") + path.count("\\")),
            "path_entropy": shannon_entropy(path),
            "has_process": 1.0 if attrs.get("process_name") else 0.0,
        })
    raise KeyError(f"no feature extractor for canonical kind {kind!r}")
