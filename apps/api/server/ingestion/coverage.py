"""Dual-write coverage reconciliation (ADR-0001 Decision C divergence guard).

The v1 ingest path is the source of truth and accepts *every* metric: dedicated
tables for the well-known ones, the open-ended ``quantity_samples`` catch-all for
the rest. The canonical dual-write only mirrors wire metrics the ontology maps for
``apple_healthkit``. So any metric the v1 path stores but the normalizer cannot map
writes **zero** canonical rows — silently. That is the "dual-write divergence" risk
ADR-0001 flagged.

This module makes the gap observable with a pure (no-DB) reconciliation between the
v1 first-class metric set and the canonical normalizer's coverage. A contract test
pins the result so a *new* silent drop-out — a v1 dedicated path added without a
canonical ontology mapping, or a mapping accidentally removed — fails loudly instead
of drifting unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass

from normalization import mapped_apple_wire_metrics

from .mappers import DAILY_ACTIVITY_QUANTITY_FIELDS, DEDICATED_TABLES

# Wire metrics the v1 ingest dispatch (``measurements._ingest_metric``) gives
# first-class handling beyond the ``quantity_samples`` catch-all. The catch-all
# accepts arbitrary metric names and so cannot be enumerated — it is out of scope
# for coverage reconciliation by construction.
_SPECIAL_CASE_METRICS = frozenset({"activity_summaries", "sleep_analysis", "workouts", "ecg"})


def v1_first_class_metrics() -> frozenset[str]:
    """Every wire metric the v1 ingest path handles with a dedicated path."""
    return frozenset(
        set(DEDICATED_TABLES) | set(DAILY_ACTIVITY_QUANTITY_FIELDS) | _SPECIAL_CASE_METRICS
    )


@dataclass(frozen=True)
class CoverageReport:
    """Dual-write coverage between the v1 ingest path and the canonical store."""

    covered: frozenset[str]  # v1 first-class AND canonical-mapped — round-trips
    v1_only: frozenset[str]  # v1 first-class but NOT canonical — silent drop-outs
    canonical_only: frozenset[str]  # canonical-mapped but not a v1 first-class path


def apple_dual_write_coverage() -> CoverageReport:
    """Reconcile v1 first-class metrics against canonical normalizer coverage."""
    v1 = v1_first_class_metrics()
    canonical = frozenset(mapped_apple_wire_metrics())
    return CoverageReport(
        covered=v1 & canonical,
        v1_only=v1 - canonical,
        canonical_only=canonical - v1,
    )
