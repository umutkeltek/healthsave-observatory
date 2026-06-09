"""SSRF guard (`analysis.netguard`) — ADR-0003 D7.

Pins the test-connection threat model: local targets and built-in cloud
endpoints pass; a cloud route with a custom base_url must be https, free of
userinfo, and resolve to a public IP. Private/loopback/link-local resolutions
are refused so the probe can't be turned on the server's own network. A stub
resolver keeps these tests off real DNS.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from analysis.egress import Destination, EgressRoute  # noqa: E402
from analysis.netguard import SsrfError, _is_public_ip, assert_safe_probe_target  # noqa: E402


def _resolver(mapping):
    def resolve(host):
        return mapping[host]

    return resolve


def test_local_route_is_always_allowed():
    # No URL check for a LOCAL target — it's inside the trust boundary.
    assert_safe_probe_target(
        EgressRoute("ollama", "http://192.168.1.50:11434"), Destination.LOCAL
    )  # would be refused as cloud, but LOCAL short-circuits


def test_cloud_with_no_base_url_uses_builtin_endpoint():
    # litellm owns the URL for a known provider; nothing to validate.
    assert_safe_probe_target(EgressRoute("deepseek"), Destination.CLOUD)


def test_cloud_custom_https_public_ip_allowed():
    route = EgressRoute("custom", "https://api.example.com/v1")
    assert_safe_probe_target(
        route, Destination.CLOUD, resolver=_resolver({"api.example.com": ["93.184.216.34"]})
    )


def test_cloud_http_scheme_refused():
    with pytest.raises(SsrfError, match="https"):
        assert_safe_probe_target(
            EgressRoute("custom", "http://api.example.com"),
            Destination.CLOUD,
            resolver=_resolver({"api.example.com": ["93.184.216.34"]}),
        )


def test_cloud_userinfo_refused():
    with pytest.raises(SsrfError, match="userinfo"):
        assert_safe_probe_target(
            EgressRoute("custom", "https://user:pass@api.example.com"),
            Destination.CLOUD,
            resolver=_resolver({"api.example.com": ["93.184.216.34"]}),
        )


def test_cloud_resolving_to_private_ip_refused():
    with pytest.raises(SsrfError, match="non-public"):
        assert_safe_probe_target(
            EgressRoute("custom", "https://sneaky.internal"),
            Destination.CLOUD,
            resolver=_resolver({"sneaky.internal": ["10.0.0.5"]}),
        )


def test_cloud_resolving_to_loopback_refused():
    with pytest.raises(SsrfError, match="non-public"):
        assert_safe_probe_target(
            EgressRoute("custom", "https://localhost-alias.example"),
            Destination.CLOUD,
            resolver=_resolver({"localhost-alias.example": ["127.0.0.1"]}),
        )


def test_cloud_mixed_public_and_private_refused():
    # If ANY resolved address is private, refuse — a rebind-style split.
    with pytest.raises(SsrfError, match="non-public"):
        assert_safe_probe_target(
            EgressRoute("custom", "https://split.example"),
            Destination.CLOUD,
            resolver=_resolver({"split.example": ["93.184.216.34", "169.254.169.254"]}),
        )


def test_cloud_unresolvable_host_refused():
    def boom(host):
        raise OSError("name resolution failed")

    with pytest.raises(SsrfError, match="did not resolve"):
        assert_safe_probe_target(
            EgressRoute("custom", "https://nope.example"),
            Destination.CLOUD,
            resolver=boom,
        )


def test_is_public_ip_classifies_ranges():
    assert _is_public_ip("8.8.8.8") is True
    assert _is_public_ip("93.184.216.34") is True
    assert _is_public_ip("10.0.0.1") is False  # private
    assert _is_public_ip("192.168.1.1") is False  # private
    assert _is_public_ip("127.0.0.1") is False  # loopback
    assert _is_public_ip("169.254.169.254") is False  # link-local (cloud metadata)
    assert _is_public_ip("::1") is False  # ipv6 loopback
    assert _is_public_ip("fd00::1") is False  # ipv6 ULA (private)
    assert _is_public_ip("not-an-ip") is False
