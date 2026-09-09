from __future__ import annotations

import pytest

from sm_contracts import CanonicalKind
from sm_ml import FEATURE_SCHEMA_VERSION, extract_features, schema_for
from sm_ml.features import shannon_entropy
from sm_ml.features.schema import FEATURE_SCHEMAS

from .conftest import canonical


def test_every_detectable_kind_has_a_schema() -> None:
    detectable = {
        CanonicalKind.auth, CanonicalKind.network_flow, CanonicalKind.dns,
        CanonicalKind.process_exec, CanonicalKind.file_access,
    }
    assert set(FEATURE_SCHEMAS) == detectable
    for schema in FEATURE_SCHEMAS.values():
        assert schema.version == FEATURE_SCHEMA_VERSION
        assert len(schema.names) == len(set(schema.names))


def test_extraction_is_deterministic() -> None:
    ev = canonical(
        CanonicalKind.auth, outcome="failure",
        actor=("identity", "svc-backup"), attributes={"source_ip": "10.0.0.9"},
    )
    v1 = extract_features(ev)
    v2 = extract_features(ev)
    assert v1 == v2
    assert v1.values["is_failure"] == 1.0
    assert v1.values["has_source_ip"] == 1.0
    assert v1.names == schema_for(CanonicalKind.auth).names
    assert len(v1.vector) == len(v1.names)


def test_values_are_clamped_to_the_schema_range() -> None:
    ev = canonical(
        CanonicalKind.network_flow,
        target=("ip", "8.8.8.8"), actor=("ip", "10.0.0.1"),
        attributes={"bytes_sent": 10**40, "dst_port": 999999, "protocol": "tcp",
                    "direction": "outbound"},
    )
    v = extract_features(ev)
    assert v.values["bytes_sent_log"] == schema_for(CanonicalKind.network_flow).spec("bytes_sent_log").hi
    assert v.values["dst_port"] == 65535.0
    assert v.values["proto_tcp"] == 1.0
    assert v.values["direction_outbound"] == 1.0


def test_dns_features_flag_long_high_entropy_names() -> None:
    ev = canonical(
        CanonicalKind.dns, actor=("ip", "10.0.0.5"),
        target=("domain", "a8f3k2j9x1q7w4.exfil.example.com"),
        attributes={"response_code": "NXDOMAIN", "query_type": "TXT", "answers": []},
    )
    v = extract_features(ev)
    assert v.values["is_nxdomain"] == 1.0
    assert v.values["qtype_is_txt"] == 1.0
    assert v.values["qname_entropy"] > 2.5
    assert v.values["label_count"] == 4.0


def test_shannon_entropy_bounds() -> None:
    assert shannon_entropy("") == 0.0
    assert shannon_entropy("aaaa") == 0.0
    assert shannon_entropy("abcd") == pytest.approx(2.0)


def test_unknown_kind_raises() -> None:
    ev = canonical(CanonicalKind.auth)
    ev_bad = ev.model_copy(update={"kind": "made_up"})
    with pytest.raises(KeyError):
        extract_features(ev_bad)
