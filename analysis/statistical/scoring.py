"""Composite health scores (Recovery, Sleep, Training Load).

See ``docs/HEALTH_DOMAIN_SUPPLEMENT.md`` §3 for the weights and
rationale. The goal is an *open* defensible formula - we publish the
math rather than hide it behind a proprietary score.
"""


def compute_recovery_score(
    hrv_vs_baseline: float,
    rhr_vs_baseline: float,
    sleep_efficiency: float,
    temp_deviation: float,
    resp_rate_vs_baseline: float,
) -> int | None:
    """Compute the 0-100 Recovery Score from the five component signals.

    Weights (from supplement §3, literature-backed):

      * HRV vs baseline - **40%** (dominant signal, every platform agrees)
      * Sleep efficiency - **25%** (the behavioral dimension users can act on)
      * RHR vs baseline - **15%** (partially redundant with HRV, catches
        overtraining when HRV crashes but RHR stays elevated)
      * Temperature deviation - **10%** (early illness signal)
      * Respiratory rate deviation - **10%** (top-2 clinical
        deterioration predictor)

    Arguments:
      hrv_vs_baseline:      % deviation from 30-day rolling mean
      rhr_vs_baseline:      % deviation (inverted - lower is better)
      sleep_efficiency:     0-100
      temp_deviation:       degrees C from personal baseline
      resp_rate_vs_baseline: % deviation

    Returns an integer 0..100 when the inputs are sufficient, or
    ``None`` when recovery scoring is suppressed (e.g. beta-blocker
    users per supplement §5.6).
    """
    raise NotImplementedError(
        "Recovery score computation deferred to Phase 1.5 - "
        "per-signal mappers and suppression rules not yet wired"
    )
