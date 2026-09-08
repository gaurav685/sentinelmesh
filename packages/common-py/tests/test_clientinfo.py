from __future__ import annotations

from sm_common.fastapi import resolve_client_ip


def test_zero_hops_ignores_forwarded_for():
    # A client cannot pick its own audited IP by sending X-Forwarded-For.
    assert (
        resolve_client_ip(peer="203.0.113.9", forwarded_for="1.2.3.4", trusted_hops=0)
        == "203.0.113.9"
    )


def test_zero_hops_with_no_peer_returns_none():
    assert resolve_client_ip(peer=None, forwarded_for="1.2.3.4", trusted_hops=0) is None


def test_one_trusted_hop_takes_the_last_forwarded_entry():
    # chain = [client, our-proxy(peer)]; with 1 trusted hop the client is chain[-2]
    assert (
        resolve_client_ip(
            peer="10.0.0.1", forwarded_for="198.51.100.7", trusted_hops=1
        )
        == "198.51.100.7"
    )


def test_two_trusted_hops_skips_the_intermediate_proxy():
    # client -> edge -> internal-proxy -> us
    assert (
        resolve_client_ip(
            peer="10.0.0.2",
            forwarded_for="198.51.100.7, 10.0.0.9",
            trusted_hops=2,
        )
        == "198.51.100.7"
    )


def test_a_client_supplied_prefix_cannot_be_reached():
    # The caller forged two leading entries; with only 1 trusted hop we still
    # land on the address our proxy actually observed, not the forged ones.
    assert (
        resolve_client_ip(
            peer="10.0.0.1",
            forwarded_for="evil-1, evil-2, 198.51.100.7",
            trusted_hops=1,
        )
        == "198.51.100.7"
    )


def test_short_chain_falls_back_to_peer():
    # Declared 3 hops but the header only has one entry: misconfig or a stripped
    # header. Do not trust a forged value; use the direct peer.
    assert (
        resolve_client_ip(peer="10.0.0.1", forwarded_for="1.2.3.4", trusted_hops=3)
        == "10.0.0.1"
    )


def test_empty_forwarded_for_returns_peer():
    assert (
        resolve_client_ip(peer="10.0.0.1", forwarded_for="", trusted_hops=2) == "10.0.0.1"
    )
    assert (
        resolve_client_ip(peer="10.0.0.1", forwarded_for="  ,  ", trusted_hops=2)
        == "10.0.0.1"
    )
