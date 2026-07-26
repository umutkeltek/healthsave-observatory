"""Composite health scores (Recovery, Sleep, Training Load).

See ``docs/HEALTH_DOMAIN_SUPPLEMENT.md`` §3 for the weights and rationale. The
goal is an *open* defensible formula — we publish the math rather than hide it
behind a proprietary score.

The composite weights come straight from the supplement. The supplement leaves
the per-signal *mapper curves* (deviation-% → 0-100 sub-score) to the
implementation; they live here as transparent, named-constant linear maps so a
critic can read them and a user can tune them:

  * ``_DEVIATION_FULL_SCALE_PCT`` — a deviation of this magnitude (in the good or
    bad direction) saturates a sub-score to 100 or 0. Baseline (0%) maps to 50.
  * ``_TEMP_FULL_PENALTY_C`` — temperature deviation in *either* direction is a
    penalty (fever or hypothermia both signal stress); this much °C drives the
    temperature sub-score to 0. Baseline (0°C) maps to 100.

Tune these two constants to reshape the curves without touching the weighting.
"""

from __future__ import annotations

# Linear mapper tuning — see module docstring. Inspectable + tunable by design.
_DEVIATION_FULL_SCALE_PCT = 20.0
_TEMP_FULL_PENALTY_C = 1.0


def _baseline_deviation_to_score(deviation_pct: float, *, higher_is_better: bool) -> float:
    """Map a %-deviation-from-baseline to a 0-100 sub-score (baseline → 50).

    ``higher_is_better`` flips the direction: for HRV a positive deviation is
    good; for resting HR / respiratory rate a *negative* deviation is good.
    Saturates to [0, 100] at ``±_DEVIATION_FULL_SCALE_PCT``.
    """
    improvement = deviation_pct if higher_is_better else -deviation_pct
    raw = 50.0 + (improvement / _DEVIATION_FULL_SCALE_PCT) * 50.0
    return max(0.0, min(100.0, raw))


def _temp_deviation_to_score(deviation_c: float) -> float:
    """Map an absolute temperature deviation (°C) to a 0-100 sub-score.

    Symmetric penalty — any deviation from the personal baseline lowers the
    score; ``_TEMP_FULL_PENALTY_C`` drives it to 0. Baseline (0°C) → 100.
    """
    penalty = (abs(deviation_c) / _TEMP_FULL_PENALTY_C) * 100.0
    return max(0.0, min(100.0, 100.0 - penalty))


def compute_recovery_score(
    hrv_vs_baseline: float | None,
    rhr_vs_baseline: float | None,
    sleep_efficiency: float | None,
    temp_deviation: float | None,
    resp_rate_vs_baseline: float | None,
) -> int | None:
    """Compute an evidence-weighted 0-100 Recovery Score.

    The published weights remain the target formula, but unavailable inputs are
    excluded rather than replaced with neutral (or accidentally ideal) values.
    Remaining weights are renormalized over the evidence actually present. The
    mapping layer enforces the minimum evidence contract before calling this
    function; this pure scorer still returns ``None`` when every input is absent.

    Weights (from supplement §3, literature-backed):

      * HRV vs baseline — **40%**
      * Sleep efficiency — **25%**
      * RHR vs baseline — **15%**
      * Temperature deviation — **10%**
      * Respiratory rate deviation — **10%**
    """
    weighted_inputs = (
        (
            0.40,
            None
            if hrv_vs_baseline is None
            else _baseline_deviation_to_score(hrv_vs_baseline, higher_is_better=True),
        ),
        (
            0.25,
            None if sleep_efficiency is None else max(0.0, min(100.0, sleep_efficiency)),
        ),
        (
            0.15,
            None
            if rhr_vs_baseline is None
            else _baseline_deviation_to_score(rhr_vs_baseline, higher_is_better=False),
        ),
        (0.10, None if temp_deviation is None else _temp_deviation_to_score(temp_deviation)),
        (
            0.10,
            None
            if resp_rate_vs_baseline is None
            else _baseline_deviation_to_score(resp_rate_vs_baseline, higher_is_better=False),
        ),
    )
    available = [(weight, score) for weight, score in weighted_inputs if score is not None]
    available_weight = sum(weight for weight, _ in available)
    if available_weight == 0:
        return None

    recovery = sum(weight * score for weight, score in available) / available_weight
    return max(0, min(100, round(recovery)))
