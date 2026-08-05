"""Resolve a client address while honoring only explicitly trusted proxies."""

from __future__ import annotations

from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

IPNetwork = IPv4Network | IPv6Network


def parse_trusted_proxy_cidrs(value: str | list[str] | None) -> tuple[IPNetwork, ...]:
    if value is None:
        return ()
    raw_values = value.split(",") if isinstance(value, str) else value
    networks: list[IPNetwork] = []
    expanded_values = [part for raw in raw_values for part in raw.split(",")]
    for raw in expanded_values:
        if not raw.strip():
            raise ValueError("trusted proxy CIDRs must be non-empty strings")
        try:
            networks.append(ip_network(raw.strip(), strict=False))
        except ValueError as exc:
            raise ValueError(f"invalid trusted proxy CIDR: {raw!r}") from exc
    return tuple(networks)


def _canonical(value: str) -> str:
    address = ip_address(value.strip())
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return str(address)


def _is_trusted(value: str, networks: Sequence[IPNetwork]) -> bool:
    address = ip_address(value)
    return any(address in network for network in networks)


def resolve_client_ip(
    direct_peer: str | None,
    forwarded_for: str | None,
    trusted_proxy_cidrs: Sequence[IPNetwork],
) -> str:
    """Return the first untrusted hop in a validated X-Forwarded-For chain.

    Headers are considered only when the directly connected peer is trusted. Any
    malformed chain falls back to that peer, preventing spoofed values from being
    used as an identity key.
    """
    if direct_peer is None or not direct_peer.strip():
        return "unknown"
    try:
        canonical_peer = _canonical(direct_peer)
    except ValueError:
        return "unknown"
    if not forwarded_for or not forwarded_for.strip() or not _is_trusted(canonical_peer, trusted_proxy_cidrs):
        return canonical_peer

    try:
        hops = [_canonical(part) for part in forwarded_for.split(",")]
    except ValueError:
        return canonical_peer
    if not hops or any(not part.strip() for part in forwarded_for.split(",")):
        return canonical_peer

    # Starting at the direct peer, trusted proxies may be peeled from the right.
    for candidate in reversed(hops):
        if not _is_trusted(candidate, trusted_proxy_cidrs):
            return candidate
    return canonical_peer
