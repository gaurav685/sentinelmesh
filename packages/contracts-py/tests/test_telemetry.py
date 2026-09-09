from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sm_contracts import (
    EVENT_PAYLOAD_REGISTRY,
    AuthEventPayload,
    AuthOutcome,
    CanonicalEventPayload,
    CanonicalKind,
    DnsQueryPayload,
    EntityKind,
    EntityRef,
    EventType,
    FileAccessPayload,
    FileAction,
    NetworkFlowPayload,
    ProcessExecPayload,
)

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def test_every_telemetry_event_type_resolves_in_the_registry():
    for et in (
        EventType.telemetry_network_flow,
        EventType.telemetry_auth_event,
        EventType.telemetry_dns_query,
        EventType.telemetry_process_exec,
        EventType.telemetry_file_access,
        EventType.event_canonical,
    ):
        assert et in EVENT_PAYLOAD_REGISTRY


# ---- NetworkFlowPayload -------------------------------------------------
def test_network_flow_validates_and_normalizes():
    p = NetworkFlowPayload(
        occurred_at=NOW, src_ip="10.0.0.1", dst_ip="93.184.216.34",
        src_port=51000, dst_port=443, protocol="TCP", app_protocol="HTTPS",
        bytes_sent=1200, packets_sent=8,
    )
    assert p.protocol == "tcp"
    assert p.app_protocol == "https"
    assert str(p.src_ip) == "10.0.0.1"
    assert p.direction.value == "unknown"


def test_network_flow_rejects_bad_ip_and_port_and_counters():
    with pytest.raises(ValidationError):
        NetworkFlowPayload(occurred_at=NOW, src_ip="not-an-ip", dst_ip="8.8.8.8", protocol="tcp")
    with pytest.raises(ValidationError):
        NetworkFlowPayload(occurred_at=NOW, src_ip="1.1.1.1", dst_ip="8.8.8.8", protocol="tcp", dst_port=70000)
    with pytest.raises(ValidationError):
        NetworkFlowPayload(occurred_at=NOW, src_ip="1.1.1.1", dst_ip="8.8.8.8", protocol="tcp", bytes_sent=-1)


def test_network_flow_end_before_start_rejected():
    with pytest.raises(ValidationError):
        NetworkFlowPayload(
            occurred_at=NOW, ended_at=NOW - timedelta(seconds=1),
            src_ip="1.1.1.1", dst_ip="8.8.8.8", protocol="tcp",
        )


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        NetworkFlowPayload(
            occurred_at=datetime(2026, 1, 1, 0, 0, 0),  # noqa: DTZ001
            src_ip="1.1.1.1", dst_ip="8.8.8.8", protocol="tcp",
        )


def test_unknown_field_forbidden():
    with pytest.raises(ValidationError):
        NetworkFlowPayload(
            occurred_at=NOW, src_ip="1.1.1.1", dst_ip="8.8.8.8", protocol="tcp", extra_field="x"
        )


# ---- AuthEventPayload -------------------------------------------------
def test_auth_failure_reason_only_on_failure():
    AuthEventPayload(
        occurred_at=NOW, outcome=AuthOutcome.failure, auth_type="ntlm",
        principal="alice@corp", failure_reason="bad password",
    )
    with pytest.raises(ValidationError):
        AuthEventPayload(
            occurred_at=NOW, outcome=AuthOutcome.success, auth_type="ntlm",
            principal="alice@corp", failure_reason="bad password",
        )


# ---- DnsQueryPayload -------------------------------------------------
def test_dns_normalizes_type_and_rcode_and_bounds_answers():
    p = DnsQueryPayload(
        occurred_at=NOW, client_ip="10.0.0.5", query_name="example.com",
        query_type="a", response_code="noerror", answers=["93.184.216.34"],
    )
    assert p.query_type == "A"
    assert p.response_code == "NOERROR"

    with pytest.raises(ValidationError):
        DnsQueryPayload(
            occurred_at=NOW, client_ip="10.0.0.5", query_name="x.com",
            query_type="A", answers=["y" * 300],
        )
    with pytest.raises(ValidationError):
        DnsQueryPayload(
            occurred_at=NOW, client_ip="10.0.0.5", query_name="x.com",
            query_type="A", answers=[""],
        )


# ---- ProcessExecPayload -------------------------------------------------
def test_process_hash_pattern_and_lowercasing():
    p = ProcessExecPayload(
        occurred_at=NOW, host="web01", process_name="curl",
        hash_sha256="A" * 64,
    )
    assert p.hash_sha256 == "a" * 64

    with pytest.raises(ValidationError):
        ProcessExecPayload(occurred_at=NOW, host="web01", process_name="curl", hash_sha256="zz")


def test_process_command_line_length_bounded():
    with pytest.raises(ValidationError):
        ProcessExecPayload(
            occurred_at=NOW, host="web01", process_name="curl", command_line="x" * 9000
        )


# ---- FileAccessPayload -------------------------------------------------
def test_file_access_action_is_an_enum():
    p = FileAccessPayload(occurred_at=NOW, host="web01", path="/etc/passwd", action=FileAction.read)
    assert p.action == FileAction.read
    with pytest.raises(ValidationError):
        FileAccessPayload(occurred_at=NOW, host="web01", path="/x", action="frobnicate")


# ---- CanonicalEventPayload -------------------------------------------------
def test_canonical_actor_and_target_must_be_in_entities():
    host = EntityRef(kind=EntityKind.host, value="web01")
    ip = EntityRef(kind=EntityKind.ip, value="8.8.8.8")

    CanonicalEventPayload(
        kind=CanonicalKind.network_flow, occurred_at=NOW, action="connected_to",
        actor=host, target=ip, entities=[host, ip],
        raw_event_id=uuid4(), raw_event_type=EventType.telemetry_network_flow,
    )

    with pytest.raises(ValidationError):
        CanonicalEventPayload(
            kind=CanonicalKind.network_flow, occurred_at=NOW, action="connected_to",
            actor=host, entities=[ip],  # actor missing from entities
            raw_event_id=uuid4(), raw_event_type=EventType.telemetry_network_flow,
        )


def test_canonical_keeps_lineage():
    raw_id = uuid4()
    p = CanonicalEventPayload(
        kind=CanonicalKind.dns, occurred_at=NOW, action="resolved",
        raw_event_id=raw_id, raw_event_type=EventType.telemetry_dns_query,
        attributes={"query_name": "evil.example"},
    )
    assert p.raw_event_id == raw_id
    assert p.raw_event_type == EventType.telemetry_dns_query
