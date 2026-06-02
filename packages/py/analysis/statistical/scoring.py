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
    hrv_vs_baseline: float,
    rhr_vs_baseline: float,
    sleep_efficiency: float,
    temp_deviation: float,
    resp_rate_vs_baseline: float,
) -> int | None:
    """Compute the 0-100 Recovery Score from the five component signals.

    Weights (from supplement §3, literature-backed):

      * HRV vs baseline — **40%** (dominant signal, every platform agrees)
      * Sleep efficiency — **25%** (the behavioral dimension users can act on)
      * RHR vs baseline — **15%** (partially redundant with HRV, catches
        overtraining when HRV crashes but RHR stays elevated)
      * Temperature deviation — **10%** (early illness signal)
      * Respiratory rate deviation — **10%** (top-2 clinical
        deterioration predictor)

    Arguments:
      hrv_vs_baseline:      % deviation from 30-day rolling mean
      rhr_vs_baseline:      % deviation (inverted — lower is better)
      sleep_efficiency:     0-100
      temp_deviation:       degrees C from personal baseline
      resp_rate_vs_baseline: % deviation

    Returns an integer 0..100. (Suppression — returning ``None`` for e.g.
    beta-blocker users per supplement §5.6 — needs a medication-context input
    this signature does not yet carry; deferred.)
    """
    hrv_score = _baseline_deviation_to_score(hrv_vs_baseline, higher_is_better=True)
    rhr_score = _baseline_deviation_to_score(rhr_vs_baseline, higher_is_better=False)
    sleep_score = max(0.0, min(100.0, sleep_efficiency))  # already 0-100; clamp defensively
    temp_score = _temp_deviation_to_score(temp_deviation)
    resp_score = _baseline_deviation_to_score(resp_rate_vs_baseline, higher_is_better=False)

    recovery = (
        0.40 * hrv_score
        + 0.25 * sleep_score
        + 0.15 * rhr_score
        + 0.10 * temp_score
        + 0.10 * resp_score
    )
    return max(0, min(100, round(recovery)))
