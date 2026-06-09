"""SSRF guard for the test-connection probe — ADR-0003 D7 (threat model).

The ``/api/v2/intelligence/test-connection`` endpoint makes a real outbound
call to verify a provider key works. That makes it a Server-Side Request
Forgery surface: a user-supplied ``base_url`` could point the server at its own
internal network (the metadata endpoint, a DB, a neighbour service). This module
is the pre-flight guard that refuses an unsafe *cloud* target before any probe
fires.

What it allows / refuses:

* A **LOCAL** route (Ollama on loopback / the bundled sidecar / a trusted host,
  as already classified by :func:`analysis.egress.classify_destination`) is by
  definition inside the trust boundary — probing it is allowed, no URL check.
* A **CLOUD** route with **no** ``base_url`` uses the provider's built-in public
  endpoint (litellm controls it) — allowed.
* A **CLOUD** route with a custom ``base_url`` must be: ``https``, carry no
  userinfo (``user:pass@``), and resolve to a **public** IP. If every resolved
  address is private / loopback / link-local / reserved / multicast, it is
  refused — a "cloud" route has no business hitting internal infra.

Residual limitation (documented, not solved here): this is a pre-call DNS check,
so a TOCTOU DNS-rebind between this check and litellm's actual connection is not
fully closed. The short timeout + ``max_tokens=1`` + no-health-data probe bound
the blast radius; a redirect-following / pinned-IP transport is future work.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

from .egress import Destination, EgressRoute

# A resolver maps a hostname to its list of IP strings. Injectable so tests
# don't depend on real DNS; defaults to the stdlib resolver.
Resolver = Callable[[str], list[str]]


class SsrfError(ValueError):
    """Raised when a cloud probe target fails the SSRF pre-flight check."""


def _default_resolver(host: str) -> list[str]:
    """Resolve ``host`` to every A/AAAA address (stdlib)."""
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def _is_public_ip(ip: str) -> bool:
    """True iff ``ip`` is a routable public address (not private/loopback/etc.)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_safe_probe_target(
    route: EgressRoute,
    destination: Destination,
    *,
    resolver: Resolver | None = None,
) -> None:
    """Raise :class:`SsrfError` if probing ``route`` would be unsafe.

    ``destination`` is the already-computed trust zone
    (:func:`analysis.egress.classify_destination`). A LOCAL target, or a CLOUD
    target with no custom ``base_url``, passes without a network check. A CLOUD
    target with a ``base_url`` is validated (https, no userinfo, public IP).
    """
    if destination is Destination.LOCAL:
        return
    base_url = route.base_url
    if not base_url:
        # Known cloud provider, built-in public endpoint — litellm owns the URL.
        return

    parsed = urlparse(base_url if "://" in base_url else f"//{base_url}")
    if parsed.scheme and parsed.scheme != "https":
        raise SsrfError(f"cloud base_url must be https, got scheme {parsed.scheme!r}")
    if not parsed.scheme:
        raise SsrfError("cloud base_url must be an absolute https URL")
    if parsed.username or parsed.password:
        raise SsrfError("cloud base_url must not embed credentials (userinfo)")
    host = parsed.hostname
    if not host:
        raise SsrfError("cloud base_url has no host")

    resolve = resolver or _default_resolver
    try:
        addresses = resolve(host)
    except OSError as exc:
        raise SsrfError(f"cloud base_url host {host!r} did not resolve: {exc}") from exc
    if not addresses:
        raise SsrfError(f"cloud base_url host {host!r} resolved to no addresses")
    unsafe = [ip for ip in addresses if not _is_public_ip(ip)]
    if unsafe:
        raise SsrfError(
            f"cloud base_url host {host!r} resolves to non-public address(es) {unsafe} "
            "— refusing to probe internal infrastructure"
        )
