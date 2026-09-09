"""Versioned feature schemas — one per `CanonicalKind` (`ml/features/`).

A `FeatureSchema` is a **contract**: an ordered list of named, bounded, float
features. Bump `FEATURE_SCHEMA_VERSION` on any change to a schema's feature set
or ordering (a model trained on v1 cannot consume v2). Every `Anomaly` row and
every model contract records the version it used.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_contracts import CanonicalKind

__all__ = [
    "FEATURE_SCHEMAS",
    "FEATURE_SCHEMA_VERSION",
    "FeatureSchema",
    "FeatureSpec",
    "schema_for",
]

FEATURE_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    lo: float
    hi: float
    description: str

    def clamp(self, value: float) -> float:
        if value < self.lo:
            return self.lo
        if value > self.hi:
            return self.hi
        return value


@dataclass(frozen=True)
class FeatureSchema:
    kind: CanonicalKind
    version: str
    specs: tuple[FeatureSpec, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.specs)

    def spec(self, name: str) -> FeatureSpec:
        for s in self.specs:
            if s.name == name:
                return s
        raise KeyError(name)


def _s(name: str, lo: float, hi: float, description: str) -> FeatureSpec:
    return FeatureSpec(name=name, lo=lo, hi=hi, description=description)


_AUTH = FeatureSchema(
    kind=CanonicalKind.auth,
    version=FEATURE_SCHEMA_VERSION,
    specs=(
        _s("is_failure", 0.0, 1.0, "1 when the authentication failed"),
        _s("hour_sin", -1.0, 1.0, "sin of the event's hour-of-day"),
        _s("hour_cos", -1.0, 1.0, "cos of the event's hour-of-day"),
        _s("day_of_week", 0.0, 6.0, "0=Monday"),
        _s("has_source_ip", 0.0, 1.0, "1 when a source IP was recorded"),
        _s("principal_len", 0.0, 64.0, "length of the principal string"),
        _s("principal_entropy", 0.0, 6.0, "Shannon entropy of the principal string"),
    ),
)

_NETWORK_FLOW = FeatureSchema(
    kind=CanonicalKind.network_flow,
    version=FEATURE_SCHEMA_VERSION,
    specs=(
        _s("bytes_sent_log", 0.0, 30.0, "ln(1 + bytes_sent)"),
        _s("bytes_received_log", 0.0, 30.0, "ln(1 + bytes_received)"),
        _s("packets_total_log", 0.0, 25.0, "ln(1 + packets_sent + packets_received)"),
        _s("dst_port", 0.0, 65535.0, "destination port"),
        _s("dst_port_is_system", 0.0, 1.0, "1 when dst_port < 1024"),
        _s("dst_port_is_ephemeral", 0.0, 1.0, "1 when dst_port >= 49152"),
        _s("proto_tcp", 0.0, 1.0, "1 when protocol is tcp"),
        _s("direction_outbound", 0.0, 1.0, "1 when direction is outbound"),
    ),
)

_DNS = FeatureSchema(
    kind=CanonicalKind.dns,
    version=FEATURE_SCHEMA_VERSION,
    specs=(
        _s("qname_len", 0.0, 253.0, "length of the query name"),
        _s("qname_entropy", 0.0, 6.0, "Shannon entropy of the query name"),
        _s("label_count", 0.0, 20.0, "number of DNS labels"),
        _s("longest_label_len", 0.0, 63.0, "longest label length"),
        _s("is_nxdomain", 0.0, 1.0, "1 when the response code is NXDOMAIN"),
        _s("answer_count", 0.0, 32.0, "number of answers"),
        _s("qtype_is_txt", 0.0, 1.0, "1 when the query type is TXT"),
    ),
)

_PROCESS_EXEC = FeatureSchema(
    kind=CanonicalKind.process_exec,
    version=FEATURE_SCHEMA_VERSION,
    specs=(
        _s("cmdline_len", 0.0, 8192.0, "length of the command line"),
        _s("cmdline_entropy", 0.0, 6.0, "Shannon entropy of the command line"),
        _s("name_entropy", 0.0, 6.0, "Shannon entropy of the process name"),
        _s("is_signed", 0.0, 1.0, "1 when the binary is signed"),
        _s("has_parent", 0.0, 1.0, "1 when a parent process name was recorded"),
        _s("path_depth", 0.0, 32.0, "number of path separators in the process path"),
    ),
)

_FILE_ACCESS = FeatureSchema(
    kind=CanonicalKind.file_access,
    version=FEATURE_SCHEMA_VERSION,
    specs=(
        _s("is_write", 0.0, 1.0, "1 for write / create"),
        _s("is_delete", 0.0, 1.0, "1 for delete"),
        _s("is_permission_change", 0.0, 1.0, "1 for permission_change"),
        _s("path_len", 0.0, 4096.0, "length of the file path"),
        _s("path_depth", 0.0, 64.0, "number of path separators"),
        _s("path_entropy", 0.0, 6.0, "Shannon entropy of the file path"),
        _s("has_process", 0.0, 1.0, "1 when an acting process was recorded"),
    ),
)

FEATURE_SCHEMAS: dict[CanonicalKind, FeatureSchema] = {
    CanonicalKind.auth: _AUTH,
    CanonicalKind.network_flow: _NETWORK_FLOW,
    CanonicalKind.dns: _DNS,
    CanonicalKind.process_exec: _PROCESS_EXEC,
    CanonicalKind.file_access: _FILE_ACCESS,
}


def schema_for(kind: CanonicalKind) -> FeatureSchema:
    try:
        return FEATURE_SCHEMAS[kind]
    except KeyError:
        raise KeyError(f"no feature schema for canonical kind {kind.value!r}") from None
