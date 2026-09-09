from __future__ import annotations

from typing import Any

from sm_contracts import CanonicalKind, EntityKind, EventType
from sm_normalization_engine.normalize import normalize


def _keys(entities: list) -> set:
    return {(e.kind, e.value) for e in entities}


def test_network_flow_maps_to_ip_to_ip_connection(make_envelope_fn: Any) -> None:
    env = make_envelope_fn(
        "network_flow", src_ip="10.0.0.1", dst_ip="93.184.216.34", protocol="TCP",
        dst_port=443, bytes_sent=1200, src_host="workstation-7", verdict="allow",
    )
    c = normalize(env)
    assert c.kind is CanonicalKind.network_flow
    assert c.action == "connected_to"
    assert c.outcome == "allow"
    assert (c.actor.kind, c.actor.value) == (EntityKind.ip, "10.0.0.1")
    assert (c.target.kind, c.target.value) == (EntityKind.ip, "93.184.216.34")
    assert (EntityKind.host, "workstation-7") in _keys(c.entities)
    assert c.attributes["protocol"] == "tcp"
    assert c.attributes["dst_port"] == 443
    assert c.raw_event_id == env.event_id
    assert c.raw_event_type is EventType.telemetry_network_flow
    assert c.occurred_at == env.occurred_at


def test_auth_failure_maps_verb_and_outcome(make_envelope_fn: Any) -> None:
    env = make_envelope_fn(
        "auth_event", outcome="failure", auth_type="ntlm", principal="alice@corp",
        target_host="dc01", source_ip="10.0.0.5", failure_reason="bad password",
    )
    c = normalize(env)
    assert c.kind is CanonicalKind.auth
    assert c.action == "authentication_failed"
    assert c.outcome == "failure"
    assert (c.actor.kind, c.actor.value) == (EntityKind.identity, "alice@corp")
    assert (c.target.kind, c.target.value) == (EntityKind.host, "dc01")
    assert (EntityKind.ip, "10.0.0.5") in _keys(c.entities)
    assert c.attributes["failure_reason"] == "bad password"


def test_dns_maps_answers_to_ip_or_domain_entities(make_envelope_fn: Any) -> None:
    env = make_envelope_fn(
        "dns_query", client_ip="10.0.0.5", query_name="evil.example",
        query_type="a", response_code="noerror", answers=["93.184.216.34", "cdn.evil.example"],
    )
    c = normalize(env)
    assert c.kind is CanonicalKind.dns
    assert c.action == "resolved"
    assert (c.target.kind, c.target.value) == (EntityKind.domain, "evil.example")
    assert (EntityKind.ip, "93.184.216.34") in _keys(c.entities)
    assert (EntityKind.domain, "cdn.evil.example") in _keys(c.entities)


def test_process_exec_actor_is_user_when_present_else_host(make_envelope_fn: Any) -> None:
    with_user = normalize(make_envelope_fn(
        "process_exec", host="web01", process_name="powershell.exe", user="corp\\svc",
        parent_process_name="explorer.exe", hash_sha256="A" * 64,
    ))
    assert (with_user.actor.kind, with_user.actor.value) == (EntityKind.identity, "corp\\svc")
    assert (EntityKind.process, "explorer.exe") in _keys(with_user.entities)
    assert with_user.attributes["hash_sha256"] == "a" * 64

    no_user = normalize(make_envelope_fn("process_exec", host="web01", process_name="curl"))
    assert (no_user.actor.kind, no_user.actor.value) == (EntityKind.host, "web01")


def test_file_access_target_is_the_path(make_envelope_fn: Any) -> None:
    c = normalize(make_envelope_fn(
        "file_access", host="web01", path="/etc/shadow", action="read", user="root",
    ))
    assert c.kind is CanonicalKind.file_access
    assert c.action == "read"
    assert (c.target.kind, c.target.value) == (EntityKind.file, "/etc/shadow")
    assert (c.actor.kind, c.actor.value) == (EntityKind.identity, "root")


def test_actor_and_target_are_always_in_entities(make_envelope_fn: Any) -> None:
    for src, fields in [
        ("network_flow", {"src_ip": "1.1.1.1", "dst_ip": "8.8.8.8", "protocol": "udp"}),
        ("auth_event", {"outcome": "success", "auth_type": "ssh", "principal": "bob"}),
        ("dns_query", {"client_ip": "1.1.1.1", "query_name": "x.com", "query_type": "A"}),
        ("process_exec", {"host": "h", "process_name": "p"}),
        ("file_access", {"host": "h", "path": "/p", "action": "write"}),
    ]:
        c = normalize(make_envelope_fn(src, **fields))
        keys = _keys(c.entities)
        assert (c.actor.kind, c.actor.value) in keys
        if c.target is not None:
            assert (c.target.kind, c.target.value) in keys
