"""Trustworthy client-IP resolution (security-model.md §5).

`X-Forwarded-For` is client-controlled. Trusting it unconditionally lets a caller
put any address in the audit log and evade per-IP rate limiting. So this only
consults it when the deployment declares how many proxies sit in front of the
service (`SM_TRUSTED_PROXY_HOPS`); with the default of `0` it returns the direct
peer address and nothing else.
"""

from __future__ import annotations

from starlette.requests import Request

__all__ = ["client_ip", "resolve_client_ip"]


def resolve_client_ip(
    *, peer: str | None, forwarded_for: str | None, trusted_hops: int
) -> str | None:
    """Return the address attributable to the client.

    `trusted_hops` is the number of reverse proxies between the client and this
    service. The address chain from the client to us is
    `[*x_forwarded_for, peer]`; the client-attributable entry is the one
    `trusted_hops` positions before the end. Anything the caller could have
    forged (the left part of `X-Forwarded-For`) is never used.
    """
    if trusted_hops <= 0 or not forwarded_for:
        return peer

    chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    if peer:
        chain.append(peer)
    if not chain:
        return peer

    index = len(chain) - 1 - trusted_hops
    if index < 0:
        # The chain is shorter than the declared hop count — a misconfiguration
        # or a stripped header. Fall back to the direct peer.
        return peer
    return chain[index]


def client_ip(request: Request, trusted_hops: int) -> str | None:
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer=peer,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_hops=trusted_hops,
    )
