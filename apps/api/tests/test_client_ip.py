from ipaddress import ip_network

from cairn_api.client_ip import parse_trusted_proxy_cidrs, resolve_client_ip


def test_direct_untrusted_peer_ignores_forwarded_header() -> None:
    assert resolve_client_ip("198.51.100.7", "203.0.113.2", (ip_network("10.0.0.0/8"),)) == "198.51.100.7"


def test_multi_hop_trusted_chain_uses_first_untrusted_from_right() -> None:
    trusted = parse_trusted_proxy_cidrs("10.0.0.0/8, 192.0.2.0/24")
    assert resolve_client_ip("10.1.1.1", "198.51.100.7, 192.0.2.3, 10.2.2.2", trusted) == "198.51.100.7"


def test_ipv4_mapped_ipv6_is_canonicalized() -> None:
    assert resolve_client_ip("::ffff:192.0.2.9", None, ()) == "192.0.2.9"


def test_empty_or_invalid_forwarded_header_falls_back_to_direct_peer() -> None:
    trusted = parse_trusted_proxy_cidrs(["10.0.0.0/8"])
    assert resolve_client_ip("10.0.0.1", "", trusted) == "10.0.0.1"
    assert resolve_client_ip("10.0.0.1", "not-an-ip", trusted) == "10.0.0.1"


def test_ipv6_cidrs_are_supported() -> None:
    trusted = parse_trusted_proxy_cidrs("2001:db8::/32")
    assert trusted == (ip_network("2001:db8::/32"),)


def test_missing_direct_peer_returns_unknown() -> None:
    assert resolve_client_ip(None, "203.0.113.2", ()) == "unknown"
