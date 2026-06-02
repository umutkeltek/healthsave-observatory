"""Dual-write coverage reconciliation — make canonical divergence observable.

ADR-0001 ships the canonical store as a best-effort mirror of the v1 source of
truth. A v1 first-class metric with no ``apple_healthkit`` ontology mapping
silently writes zero canonical rows. This test pins the current coverage so a
NEW silent drop-out — a v1 dedicated path added without a canonical mapping, or
a mapping accidentally removed — fails loudly instead of drifting unnoticed.
"""

from __future__ import annotations

from server.ingestion.coverage import apple_dual_write_coverage, v1_first_class_metrics


def test_report_partitions_the_v1_first_class_set() -> None:
    report = apple_dual_write_coverage()
    v1 = v1_first_class_metrics()
    # covered + v1_only exactly partition the v1 first-class metrics.
    assert report.covered | report.v1_only == v1
    assert report.covered & report.v1_only == frozenset()
    # covered is the intersection, so it never overlaps canonical_only.
    assert report.covered & report.canonical_only == frozenset()


def test_core_vitals_round_trip_into_the_canonical_store() -> None:
    """heart_rate + HRV are load-bearing — the read API and the narrator go
    blind without them in the canonical store. Guard against a mapping
    regression that would silently stop mirroring them."""
    report = apple_dual_write_coverage()
    assert {"heart_rate", "heart_rate_variability"} <= report.covered


def test_silent_dropouts_are_an_explicit_reviewed_set() -> None:
    """Every v1 first-class metric that does NOT reach the canonical store must
    be listed here, with a reason. Changing the v1 dispatch or the ontology
    mappings shifts this set and fails the test — surfacing the divergence for a
    deliberate decision (ADR-0001 dual-write divergence risk).
    """
    report = apple_dual_write_coverage()
    known_deferred = {
        # ECG: v1 persists only the average-HR scalar; no canonical metric models
        # the ECG event yet (waveform/event support is a later ontology phase).
        "ecg",
        # `activity_summaries` is an envelope — its component totals (step_count,
        # active_energy_burned, …) ARE covered individually. The summary wire
        # name itself has no canonical metric, by design.
        "activity_summaries",
    }
    assert set(report.v1_only) == known_deferred
