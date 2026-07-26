"""Recovery Score mapping — period summary → ``compute_recovery_score`` inputs.

Bridges the canonical period summary (``DataAggregator.summarize_period``) to the
open composite in :mod:`analysis.statistical.scoring`. Brain-1 only: the single
import is its sibling ``scoring`` — no DB, no HTTP, no LLM.

**Evidence contract.** A score is produced only when at least three of the five
published inputs are available and one is an autonomic anchor (HRV or resting
heart rate). Missing inputs are excluded and the remaining published weights are
renormalized; they are never replaced with neutral or ideal values. Sleep
currently remains unavailable from this scalar summary, so today's score needs
three of the four wearable inputs and is explicitly marked partial.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .scoring import compute_recovery_score

# Canonical metric_ids the recovery composite reads (see contracts/ontology.py).
HRV_METRIC = "vital.hrv_sdnn"
RHR_METRIC = "vital.resting_heart_rate"
RESP_METRIC = "vital.respiratory_rate"
# Apple Watch overnight wrist-temperature deviation — already a baseline-relative
# °C delta, so its window average IS the temperature deviation (preferred).
WRIST_TEMP_DEVIATION_METRIC = "vital.wrist_temperature_deviation"
# Absolute body temperature — fallback; deviation = window avg − 30-day baseline.
BODY_TEMP_METRIC = "body.temperature"

# The metric set the recovery run must summarize. body.temperature and the wrist
# deviation are NOT in the aggregator's default scalar list, so the run passes
# this explicitly (see analysis.engine.run_recovery_check).
RECOVERY_INPUT_METRICS: tuple[str, ...] = (
    HRV_METRIC,
    RHR_METRIC,
    RESP_METRIC,
    WRIST_TEMP_DEVIATION_METRIC,
    BODY_TEMP_METRIC,
)

# Evidence contract for a user-facing composite. A single healthy-looking input
# must never create a complete-looking recovery instrument.
_RECOVERY_INPUT_COUNT = 5
_MIN_AVAILABLE_INPUTS = 3
_INPUT_WEIGHTS = {
    "hrv": 0.40,
    "sleep_efficiency": 0.25,
    "resting_heart_rate": 0.15,
    "temperature": 0.10,
    "respiratory_rate": 0.10,
}
_AUTONOMIC_INPUTS = frozenset({"hrv", "resting_heart_rate"})


def _delta_pct(metrics: Mapping[str, Mapping[str, Any]], metric_id: str) -> float | None:
    """%-deviation-from-baseline for ``metric_id``, or None when unavailable.

    None covers both "metric absent from the window" and "metric present but no
    baseline to compare against" — either way there is no honest deviation to
    feed the composite.
    """
    metric = metrics.get(metric_id)
    if not metric:
        return None
    delta = metric.get("delta_pct_vs_baseline")
    return float(delta) if delta is not None else None


def _temperature_deviation_c(metrics: Mapping[str, Mapping[str, Any]]) -> float | None:
    """Temperature deviation from personal baseline, in °C (None when absent).

    Prefers Apple Watch overnight wrist-temperature deviation, which is already a
    baseline-relative °C delta — its window average is used directly. Falls back
    to absolute body temperature minus its 30-day baseline average.
    """
    deviation = metrics.get(WRIST_TEMP_DEVIATION_METRIC)
    if deviation and deviation.get("avg") is not None:
        return float(deviation["avg"])
    body = metrics.get(BODY_TEMP_METRIC)
    if body and body.get("avg") is not None and body.get("baseline_avg") is not None:
        return float(body["avg"]) - float(body["baseline_avg"])
    return None


def recovery_finding_data(
    metrics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Map a period summary's per-metric dict to a ``recovery_score`` finding.

    Returns the ``structured_data`` payload for a ``recovery_score`` finding, or
    ``None`` when no real recovery signal is present (the caller then skips the
    run instead of persisting a fabricated score).
    """
    hrv = _delta_pct(metrics, HRV_METRIC)
    rhr = _delta_pct(metrics, RHR_METRIC)
    resp = _delta_pct(metrics, RESP_METRIC)
    temp = _temperature_deviation_c(metrics)

    inputs = (
        ("hrv", hrv),
        ("resting_heart_rate", rhr),
        ("respiratory_rate", resp),
        ("temperature", temp),
    )
    signals_available = [name for name, value in inputs if value is not None]
    if len(signals_available) < _MIN_AVAILABLE_INPUTS or not (
        _AUTONOMIC_INPUTS & set(signals_available)
    ):
        return None

    # Sleep efficiency is not derivable from the scalar summary yet. Keep it
    # absent and renormalize over real inputs; do not let a placeholder influence
    # the result.
    score = compute_recovery_score(
        hrv_vs_baseline=hrv,
        rhr_vs_baseline=rhr,
        sleep_efficiency=None,
        temp_deviation=temp,
        resp_rate_vs_baseline=resp,
    )
    if score is None:  # defensive: the evidence gate above guarantees inputs
        return None

    missing_inputs = [name for name, value in inputs if value is None]
    missing_inputs.append("sleep_efficiency")
    available_weight = sum(_INPUT_WEIGHTS[name] for name in signals_available)
    evidence_level = "complete" if len(signals_available) == _RECOVERY_INPUT_COUNT else "partial"

    return {
        "score": score,
        "method": "supplement_v2_available_weight",
        "formula_version": 2,
        "signals_available": signals_available,
        "missing_inputs": missing_inputs,
        "input_count": len(signals_available),
        "input_total": _RECOVERY_INPUT_COUNT,
        "available_weight": round(available_weight, 2),
        "evidence_level": evidence_level,
        "contributors": {
            "hrv_vs_baseline_pct": hrv,
            "rhr_vs_baseline_pct": rhr,
            "respiratory_rate_vs_baseline_pct": resp,
            "temperature_deviation_c": temp,
            "sleep_efficiency": None,
        },
    }
