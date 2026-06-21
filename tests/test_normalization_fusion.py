"""Guardrail tests for the pure cross-path fusion core (normalization.fusion).

These encode the non-negotiable rules from VENDOR_CONNECTORS.md: never fuse on
time/value alone, identity-gate first, never sum across aggregation scopes, and
direct-beats-relayed only at equal granularity.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from normalization.fusion import (
    AggregationScope,
    DeviceLinkConfidence,
    FusionDecision,
    SessionCandidate,
    VariantTier,
    can_sum,
    decide_session_fusion,
    exact_ingest_key,
    select_primary,
    semantic_key,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
SOURCE = UUID("11111111-1111-1111-1111-111111111111")


# --- aggregation scope: never sum across scopes -------------------------------


def test_can_sum_only_interval_components() -> None:
    assert can_sum(AggregationScope.INTERVAL_COMPONENT, AggregationScope.INTERVAL_COMPONENT)
    assert not can_sum(AggregationScope.DEVICE_DAY_TOTAL, AggregationScope.INTERVAL_COMPONENT)
    assert not can_sum(
        AggregationScope.OWNER_ALL_SOURCE_DAY_TOTAL, AggregationScope.DEVICE_DAY_TOTAL
    )
    assert not can_sum(
        AggregationScope.PROVIDER_RECONCILED_DAY_TOTAL,
        AggregationScope.PROVIDER_ACCOUNT_DAY_TOTAL,
    )


# --- exact_ingest_key: idempotency, revision-independent ----------------------


def test_exact_ingest_key_provider_id_is_stable_and_distinct() -> None:
    a = exact_ingest_key(OWNER, SOURCE, "exercise", provider_object_id="E1")
    assert a == exact_ingest_key(OWNER, SOURCE, "exercise", provider_object_id="E1")
    assert a != exact_ingest_key(OWNER, SOURCE, "exercise", provider_object_id="E2")
    assert a.startswith("xik:v1:")


def test_exact_ingest_key_falls_back_to_composite() -> None:
    k = exact_ingest_key(OWNER, SOURCE, "steps", fallback_fields=("2026-06-21", 8153))
    assert k == exact_ingest_key(OWNER, SOURCE, "steps", fallback_fields=("2026-06-21", 8153))
    assert k != exact_ingest_key(OWNER, SOURCE, "steps", fallback_fields=("2026-06-21", 9000))


def test_exact_ingest_key_requires_identity() -> None:
    with pytest.raises(ValueError):
        exact_ingest_key(OWNER, SOURCE, "exercise")


# --- semantic_key: provider-rooted, null without strong identity --------------


def test_semantic_key_null_without_provider_identity() -> None:
    # The Health-Connect-relayed case: no provider object id at ingest -> null.
    assert semantic_key("polar", "user-1", "exercise", None) is None
    assert semantic_key("polar", None, "exercise", "E1") is None


def test_semantic_key_provider_rooted_when_strong() -> None:
    assert semantic_key("polar", "user-1", "exercise", "E1") == "sem:v1:polar:user-1:exercise:E1"


# --- decide_session_fusion: identity-gated, time/value never alone ------------


def _session(**kw: object) -> SessionCandidate:
    base = dict(
        vendor_family="polar",
        activity_type="RUNNING",
        start_epoch_s=1_000.0,
        end_epoch_s=4_600.0,
        provider_object_id="E1",
    )
    base.update(kw)
    return SessionCandidate(**base)  # type: ignore[arg-type]


def test_fuse_when_vendor_device_activity_and_interval_agree() -> None:
    direct = _session()
    relayed = _session(provider_object_id=None, start_epoch_s=1_001.0, end_epoch_s=4_599.0)
    d = decide_session_fusion(direct, relayed, DeviceLinkConfidence.STRONG)
    assert d == FusionDecision(True, "vendor + device-link + activity + interval all agree")


def test_no_fuse_on_matching_time_value_with_weak_device_link() -> None:
    # The "72 bpm at 10:00" guardrail: identical interval, but the device link is
    # only package+model deep -> must NOT fuse.
    direct = _session()
    relayed = _session(provider_object_id=None)
    assert not decide_session_fusion(direct, relayed, DeviceLinkConfidence.WEAK).fuse


def test_no_fuse_across_vendors_even_if_identical_interval() -> None:
    direct = _session()
    relayed = _session(vendor_family="garmin", provider_object_id=None)
    assert not decide_session_fusion(direct, relayed, DeviceLinkConfidence.STRONG).fuse


def test_no_fuse_on_activity_mismatch() -> None:
    direct = _session()
    relayed = _session(activity_type="CYCLING", provider_object_id=None)
    assert not decide_session_fusion(direct, relayed, DeviceLinkConfidence.STRONG).fuse


def test_no_fuse_on_boundary_drift() -> None:
    direct = _session()
    relayed = _session(provider_object_id=None, start_epoch_s=1_010.0)  # +10s > 5s
    assert not decide_session_fusion(direct, relayed, DeviceLinkConfidence.STRONG).fuse


def test_no_fuse_without_direct_provider_id() -> None:
    direct = _session(provider_object_id=None)
    relayed = _session(provider_object_id=None)
    assert not decide_session_fusion(direct, relayed, DeviceLinkConfidence.STRONG).fuse


# --- select_primary: direct beats relayed, equal granularity only -------------


def test_select_primary_prefers_direct() -> None:
    tiers = [VariantTier.HC_PACKAGE_AND_DEVICE, VariantTier.DIRECT_WITH_PROVIDER_ID]
    assert select_primary(tiers) == 1


def test_select_primary_empty_is_none() -> None:
    assert select_primary([]) is None
