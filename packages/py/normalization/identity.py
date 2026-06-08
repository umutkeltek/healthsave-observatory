"""Source/Device/Stream identity — the pure, deterministic core (R2 Track A).

Persistence + lookup live in ``storage.timescale.registry``; this module is the
referentially-transparent half: deterministic **stream UUIDs** + origin
normalization. A stream id, once derived for a given (owner, plugin, origin), is
stable forever — Home Assistant entities key on it, so it must never drift.

Model recap (see docs/architecture/SOURCE_DEVICE_MODEL.md):
- **Source** = the *integration* the data entered through (e.g. apple-healthkit-ios).
- **Device** = the *emitter* (Apple Watch, WHOOP band, …).
- **Stream** = the join "this device via this integration", with a stable UUID.
  The same band seen via HealthKit and via a direct OAuth poll = two streams.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

# Integration ("source") plugin ids.
APPLE_HEALTHKIT_PLUGIN = "apple-healthkit-ios"

# Fixed namespace for uuid5 stream ids. NEVER change this constant — doing so
# would re-key every stream and orphan every HA entity built on the old ids.
STREAM_NAMESPACE = UUID("9e1b7c34-5a2d-4f6e-8b0a-3c7d9f1e2a64")

_UNKNOWN_ORIGIN = "unknown"


def normalize_origin(raw_source: str | None) -> str:
    """Normalize a raw origin label (HK source name / provider label) to a stable key.

    Case-folded, whitespace-collapsed. Missing/blank → a single ``unknown``
    sentinel so identity never depends on absent provenance.
    """
    if not raw_source:
        return _UNKNOWN_ORIGIN
    key = " ".join(raw_source.strip().lower().split())
    return key or _UNKNOWN_ORIGIN


def stream_id(owner_id: UUID, plugin_id: str, origin_key: str) -> UUID:
    """Deterministic stream UUID for (owner, integration, origin).

    uuid5 over a fixed namespace → same inputs always yield the same id, with no
    coordination or DB round-trip. The origin is normalized by the caller (or via
    :func:`resolve_apple_origin`).
    """
    return uuid5(STREAM_NAMESPACE, f"{owner_id}:{plugin_id}:{origin_key}")


@dataclass(frozen=True)
class ResolvedStream:
    """The identity a raw sample resolves to."""

    source_plugin_id: str
    origin_key: str
    device_label: str
    stream_id: UUID


def resolve_apple_origin(owner_id: UUID, raw_source: str | None) -> ResolvedStream:
    """Resolve a ``/api/apple/batch`` sample's ``source`` to a stable stream identity.

    The integration is always ``apple-healthkit-ios`` for this path; the raw
    ``source`` string is a HealthKit origin alias (the emitting device/app), NOT a
    Source. The human-readable label is preserved for display.
    """
    origin = normalize_origin(raw_source)
    label = (raw_source or "").strip() or "Unknown"
    return ResolvedStream(
        source_plugin_id=APPLE_HEALTHKIT_PLUGIN,
        origin_key=origin,
        device_label=label,
        stream_id=stream_id(owner_id, APPLE_HEALTHKIT_PLUGIN, origin),
    )
