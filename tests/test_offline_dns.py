"""The shared DNS fixture preserves local sockets and real SSRF validation."""
import ipaddress
import socket

import pytest

from animan import security


def test_fixture_domains_resolve_offline_with_original_socket_parameters():
    result = socket.getaddrinfo("unresolvable-fixture.invalid", 8765, socket.AF_INET, socket.SOCK_DGRAM)
    assert result == [(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, "", ("93.184.216.34", 8765))]
    assert security.is_safe_url("https://unresolvable-fixture.invalid/episode")


@pytest.mark.parametrize("host", ["localhost", "localhost.", "player.localhost", "127.0.0.1", "10.0.0.1", "::1"])
def test_loopback_and_private_addresses_remain_private(host):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    result = socket.getaddrinfo(host, 8080, family, socket.SOCK_STREAM)
    assert all(security.is_ip_blocked(ipaddress.ip_address(item[4][0])) for item in result)
    url_host = f"[{host}]" if ":" in host else host
    assert not security.is_safe_url(f"http://{url_host}:8080/")


@pytest.mark.parametrize("addresses", [[], ["127.0.0.1"], ["93.184.216.34", "10.0.0.1"], None])
def test_security_tests_can_override_dns_without_stale_cache(monkeypatch, addresses):
    # Reuse the same hostname in each case: a previous cached public result
    # must not hide a failed resolution or a private answer in the next test.
    assert "cache-fixture.example" not in security._DNS_CACHE
    assert security.is_safe_url("https://cache-fixture.example")
    security._DNS_CACHE.clear()

    def resolve(*args, **kwargs):
        if addresses is None:
            raise socket.gaierror(socket.EAI_NONAME, "Test resolution failure")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert not security.is_safe_url("https://cache-fixture.example")
