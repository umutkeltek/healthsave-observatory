"""Cross-path fusion — the pure, deterministic core (vendor-connectors R5/R6).

Companion to :mod:`normalization.identity` (which derives stable Source/Device/
Stream UUIDs). This module is the referentially-transparent half of the decision
locked in ``docs_private/architecture/VENDOR_CONNECTORS.md``:

    The same physical device can reach the Observatory by TWO paths — relayed
    through Android Health Connect (often without a stable provider id) AND polled
    directly from the vendor cloud (strong provider ids). Both are kept as distinct
    streams; reads *fuse* them. The hard rule, from two independent GPT-5.5 Pro
    consults:

    **`semantic_key` is a recomputable fusion *assertion*, assigned AFTER provider
    + device identity is resolved — never a timestamp/value fingerprint computed at
    ingest.** A bare ``(metric, rounded_time, value)`` key eventually merges two
    genuine devices (Apple-Watch HR and a WHOOP band can both read 72 bpm at 10:00).

Two keys, two jobs:
- :func:`exact_ingest_key` — source-local idempotency (immutable; protects writes).
- :func:`semantic_key` — cross-path equivalence (nullable; assigned by matching).

No DB, no HTTP, no clock. Persistence (``canonical_observations`` columns, the
``fusion_decisions`` audit trail, ``device_identity_links``) is a later slice that
consumes these functions; keeping the rules pure makes the guardrails unit-testable
before any of that lands.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from uuid import UUID


class AggregationScope(StrEnum):
    """What a cumulative value actually covers. Values across scopes are NEVER
    summed and NEVER fused — a daily total is not its own 15-minute components,
    and a provider/all-source aggregate is not a single device's contribution."""

    INTERVAL_COMPONENT = "interval_component"
    DEVICE_DAY_TOTAL = "device_day_total"
    PROVIDER_ACCOUNT_DAY_TOTAL = "provider_account_day_total"
    PROVIDER_RECONCILED_DAY_TOTAL = "provider_reconciled_day_total"
    OWNER_ALL_SOURCE_DAY_TOTAL = "owner_all_source_day_total"


class DeviceLinkConfidence(StrEnum):
    """Confidence that an HC stream and a direct stream are the same emitter.
    Manufacturer/model is evidence, not identity — only STRONG (or user-confirmed)
    may auto-link; never auto-link when two same-model devices are plausible."""

    NONE = "none"
    WEAK = "weak"  # package + manufacturer/model only
    MEDIUM = "medium"  # one active same-model device + longitudinal correlation
    STRONG = "strong"  # provider serial / HC stable device id / user-confirmed


def can_sum(a: AggregationScope, b: AggregationScope) -> bool:
    """Two cumulative values may be added only if they are the same component
    scope. Totals, account aggregates, and reconciled aggregates are terminal."""
    return a is b is AggregationScope.INTERVAL_COMPONENT


def _digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def exact_ingest_key(
    owner_id: UUID,
    source_id: UUID,
    object_type: str,
    *,
    provider_object_id: str | None = None,
    fallback_fields: tuple[object, ...] = (),
) -> str:
    """Source-local idempotency key. Prefers the provider's stable object id; falls
    back to a composite of normalized fields. The provider *revision* timestamp is
    deliberately excluded — a revised object is the same ingest identity."""
    if provider_object_id:
        return "xik:v1:" + _digest(owner_id, source_id, object_type, provider_object_id)
    if not fallback_fields:
        raise ValueError("exact_ingest_key needs a provider_object_id or fallback_fields")
    return "xik:v1:" + _digest(owner_id, source_id, object_type, "composite", *fallback_fields)


def semantic_key(
    vendor_family: str,
    provider_subject_id: str | None,
    object_type: str,
    provider_object_id: str | None,
) -> str | None:
    """Provider-rooted equivalence anchor for a *direct* record. Returns ``None``
    when there is no strong provider identity (the normal Health-Connect-relayed
    case at ingest) — fusion fills it in later, it is never invented from time/value."""
    if not (provider_subject_id and provider_object_id):
        return None
    return f"sem:v1:{vendor_family}:{provider_subject_id}:{object_type}:{provider_object_id}"


@dataclass(frozen=True)
class SessionCandidate:
    """A workout/exercise/sleep session up for cross-path matching."""

    vendor_family: str
    activity_type: str
    start_epoch_s: float
    end_epoch_s: float
    provider_object_id: str | None  # present on direct records, absent via HC

    @property
    def duration_s(self) -> float:
        return self.end_epoch_s - self.start_epoch_s


@dataclass(frozen=True)
class FusionDecision:
    """The result of a match attempt — recorded verbatim in ``fusion_decisions``."""

    fuse: bool
    reason: str


# Conservative initial thresholds (VENDOR_CONNECTORS.md §3). Bias to NON-merge: a
# false split shows visible duplicates; a false merge silently destroys provenance.
_MAX_BOUNDARY_DRIFT_S = 5.0
_MIN_OVERLAP_RATIO = 0.98


def decide_session_fusion(
    direct: SessionCandidate,
    relayed: SessionCandidate,
    device_link: DeviceLinkConfidence,
) -> FusionDecision:
    """Decide whether a Health-Connect-relayed session is the same logical event as
    a direct vendor session. Identity-gated FIRST, then time/shape as corroboration —
    never the reverse. This is the Polar first-slice primitive."""
    if direct.provider_object_id is None:
        return FusionDecision(False, "no direct provider object id to anchor the match")
    if direct.vendor_family != relayed.vendor_family:
        return FusionDecision(False, "different vendor families")
    if device_link not in (DeviceLinkConfidence.STRONG, DeviceLinkConfidence.MEDIUM):
        return FusionDecision(False, f"device link too weak to fuse ({device_link.value})")
    if direct.activity_type != relayed.activity_type:
        return FusionDecision(False, "activity type mismatch")
    if abs(direct.start_epoch_s - relayed.start_epoch_s) > _MAX_BOUNDARY_DRIFT_S:
        return FusionDecision(False, "start times differ beyond tolerance")
    if abs(direct.end_epoch_s - relayed.end_epoch_s) > _MAX_BOUNDARY_DRIFT_S:
        return FusionDecision(False, "end times differ beyond tolerance")
    overlap = min(direct.end_epoch_s, relayed.end_epoch_s) - max(
        direct.start_epoch_s, relayed.start_epoch_s
    )
    span = max(direct.duration_s, relayed.duration_s)
    if span <= 0 or overlap / span < _MIN_OVERLAP_RATIO:
        return FusionDecision(False, "interval overlap below threshold")
    return FusionDecision(True, "vendor + device-link + activity + interval all agree")


# Primary-selection order for variants that ARE the same logical observation, at
# EQUAL granularity (VENDOR_CONNECTORS.md §3). Lower rank = preferred ("direct wins").
class VariantTier(IntEnum):
    DIRECT_WITH_PROVIDER_ID = 0
    DIRECT_WITH_DEVICE = 1
    HC_WITH_RECORD_UID = 2
    HC_PACKAGE_AND_DEVICE = 3
    HC_PACKAGE_ONLY = 4
    UNKNOWN = 5


def select_primary(tiers: list[VariantTier]) -> int | None:
    """Index of the primary variant (lowest tier). ``None`` for an empty list.

    Caller MUST only pass variants of equal semantic granularity — a device-specific
    HC reading must never lose to a direct *account aggregate*; those are different
    groups, not competing variants of one observation."""
    if not tiers:
        return None
    return min(range(len(tiers)), key=lambda i: tiers[i].value)
