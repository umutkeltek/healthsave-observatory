"""R2 Track A — pure Source/Device/Stream identity resolver (deterministic core).

The *pure* half of the resolver: turning (owner, integration, raw origin) into a
**stable, deterministic stream UUID** with no DB. Persistence/lookup lives in the
storage registry repo; this is the part that must be referentially transparent and
unit-testable in isolation. A stream id, once derived for a given (owner, plugin,
origin), must never change — HA entities will key on it.
"""

from __future__ import annotations

from uuid import UUID

from normalization import identity


def test_normalize_origin_is_stable_and_safe():
    assert identity.normalize_origin("Apple Watch") == identity.normalize_origin("apple watch")
    assert identity.normalize_origin("  WHOOP  ") == identity.normalize_origin("whoop")
    # empty / missing collapse to a single sentinel, never crash
    assert identity.normalize_origin(None) == identity.normalize_origin("")
    assert identity.normalize_origin(None) == identity.normalize_origin("   ")


def test_stream_id_is_deterministic():
    owner = UUID("00000000-0000-0000-0000-000000000001")
    a = identity.stream_id(owner, identity.APPLE_HEALTHKIT_PLUGIN, "apple watch")
    b = identity.stream_id(owner, identity.APPLE_HEALTHKIT_PLUGIN, "apple watch")
    assert isinstance(a, UUID)
    assert a == b  # same inputs -> same UUID, forever


def test_stream_id_separates_device_plugin_and_owner():
    owner = UUID("00000000-0000-0000-0000-000000000001")
    other_owner = UUID("00000000-0000-0000-0000-000000000002")
    watch = identity.stream_id(owner, identity.APPLE_HEALTHKIT_PLUGIN, "apple watch")
    whoop = identity.stream_id(owner, identity.APPLE_HEALTHKIT_PLUGIN, "whoop")
    via_oauth = identity.stream_id(owner, "whoop-oauth", "whoop")
    other = identity.stream_id(other_owner, identity.APPLE_HEALTHKIT_PLUGIN, "apple watch")
    # same band seen two ways = two streams; different device/owner = different stream
    assert len({watch, whoop, via_oauth, other}) == 4


def test_resolve_apple_origin_returns_full_identity():
    owner = UUID("00000000-0000-0000-0000-000000000001")
    r = identity.resolve_apple_origin(owner, "Apple Watch")
    assert r.source_plugin_id == identity.APPLE_HEALTHKIT_PLUGIN
    assert r.origin_key == identity.normalize_origin("Apple Watch")
    assert r.device_label == "Apple Watch"  # display label preserved
    assert r.stream_id == identity.stream_id(owner, identity.APPLE_HEALTHKIT_PLUGIN, "apple watch")


def test_resolve_apple_origin_handles_missing_source():
    owner = UUID("00000000-0000-0000-0000-000000000001")
    r = identity.resolve_apple_origin(owner, None)
    assert r.source_plugin_id == identity.APPLE_HEALTHKIT_PLUGIN
    assert isinstance(r.stream_id, UUID)  # never crashes; resolves to an "unknown" stream
