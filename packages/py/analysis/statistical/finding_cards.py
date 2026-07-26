"""Deterministic Finding Card builders — the content model, computed.

Brain-1, pure: each function turns one persisted finding's ``structured_data``
(the math the detectors already did) into a :class:`contracts.findings.FindingCard`.
No DB, no HTTP, no LLM — this module imports only ``contracts`` and its pure
sibling :mod:`analysis.statistical.experiment_readiness`, so it unit-tests
without a database and never violates the two-brain seal (the narrator later
renders these cards; it never builds one).

The single entry point is :func:`build_card`, which the analysis engine calls at
its one finding-insertion seam. It dispatches on ``finding_type``; an unknown
type (or a finding too thin to describe honestly) returns ``None`` so the finding
still persists with a ``NULL`` card and is served as ``schema_version 0``.

Field provenance (all deterministic, from existing math):
* delta / effect size  → the detector's own numbers (z-score, Spearman ρ, slope,
  %-vs-baseline).
* coverage             → the ``gates.py`` sufficiency thresholds the finding cleared.
* confounders          → the detectors' context suppressions (post-workout HRV
  downgrade, etc.).
* next_question        → rule-generated per type; correlations additionally carry
  a promotable :class:`ExperimentCandidateRef` via the readiness classifier.
"""

from __future__ import annotations

from typing import Any

from contracts.findings import (
    Confounder,
    Coverage,
    Delta,
    EffectSize,
    ExperimentCandidateRef,
    FindingCard,
    NextQuestion,
    WindowRef,
)

from . import experiment_readiness as readiness
from .gates import MINIMUM_DATA_REQUIREMENTS

# A "ran X% vs baseline" delta claim needs enough samples in the window to be
# meaningful — a single reading's %-vs-baseline is noise, not a signal. No entry
# in MINIMUM_DATA_REQUIREMENTS fits (``weekly_summary`` is day-based, not
# observation-based, so reusing it would conflate days with samples), so we name
# a conservative sample floor here. Below it, a summary card drops the delta
# claim and says why, rather than asserting a percentage it can't stand behind.
_SUMMARY_DELTA_MIN_SAMPLES = 5


def _short(metric_id: str | None) -> str:
    """Human tail of a metric id (``vital.resting_heart_rate`` → ``resting heart rate``)."""
    if not metric_id:
        return "this metric"
    return readiness._short(metric_id)


def _severity_confidence(severity: str | None) -> str | None:
    """Map a finding's severity band onto card confidence (statistical certainty)."""
    return {"alert": "high", "watch": "medium", "info": "low"}.get(severity or "")


def _p_confidence(p_value: float | None) -> str | None:
    """Confidence from a significance level (p<0.01 high, p<0.05 medium, else low)."""
    if p_value is None:
        return None
    if p_value < 0.01:
        return "high"
    if p_value < 0.05:
        return "medium"
    return "low"


def _z_label(z: float) -> str:
    az = abs(z)
    if az >= 3.0:
        return "large"
    if az >= 2.5:
        return "moderate"
    return "small"


def _rho_label(rho: float) -> str:
    a = abs(rho)
    if a >= 0.7:
        return "strong"
    if a >= 0.5:
        return "moderate"
    return "weak"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


# ──────────────────────────────────────────────────────────────────
#  Per-type builders
# ──────────────────────────────────────────────────────────────────


def _anomaly_card(
    metric: str | None, sd: dict[str, Any], severity: str | None
) -> FindingCard | None:
    z = _num(sd.get("magnitude"))
    if metric is None or z is None:
        return None
    direction = sd.get("direction")
    context = sd.get("context") if isinstance(sd.get("context"), dict) else {}
    value = _num(context.get("value"))
    baseline_mean = _num(context.get("baseline_mean"))

    above_below = "above" if direction == "up" else "below"
    claim = f"{_short(metric)} was {abs(z):.1f}σ {above_below} your personal baseline"

    delta = None
    if value is not None and baseline_mean is not None:
        delta = Delta(
            absolute=value - baseline_mean,
            direction="up" if direction == "up" else "down" if direction == "down" else "flat",
        )

    confounders: list[Confounder] = []
    if context.get("downgrade_reason") == "post_workout":
        confounders.append(
            Confounder(
                kind="post_workout",
                description=(
                    "a workout within the preceding 4 hours likely explains part of "
                    "this deviation — severity was downgraded accordingly"
                ),
                metric=metric,
            )
        )

    req = MINIMUM_DATA_REQUIREMENTS["anomaly_detection"]
    return FindingCard(
        claim=claim,
        metric=metric,
        finding_type="anomaly",
        current_window=WindowRef(label="detection window", end=_parse_dt(sd.get("detected_at"))),
        baseline_window=WindowRef(label="preceding personal baseline"),
        delta=delta,
        effect_size=EffectSize(value=z, kind="z_score", label=_z_label(z)),
        coverage=Coverage(
            is_sufficient=True,
            note=(
                f"cleared ≥{int(req['min_observations'])} observations over "
                f"≥{int(req['min_days'])} days of baseline"
            ),
        ),
        confidence=_severity_confidence(severity),
        confounders=confounders,
        next_question=NextQuestion(
            prose=(
                f"Does {_short(metric)} return toward baseline over the next few days, "
                "or is this the start of a new regime?"
            )
        ),
    )


def _trend_card(metric: str | None, sd: dict[str, Any]) -> FindingCard | None:
    slope = _num(sd.get("slope"))
    if metric is None or slope is None:
        return None
    direction = sd.get("direction")
    period_days = sd.get("period_days")
    p_value = _num(sd.get("p_value"))

    claim = f"{_short(metric)} is trending {direction or 'flat'} over the last {period_days} days"
    req = MINIMUM_DATA_REQUIREMENTS["trend_analysis"]
    return FindingCard(
        claim=claim,
        metric=metric,
        finding_type="trend",
        # The Trend model carries only the regression *span* (period_days), not
        # the count of observations the fit ran on — a 30-day span may hold ~21
        # points. Reporting the span as ``n`` would overstate coverage, so ``n``
        # is left null and the span lives in the label only.
        current_window=WindowRef(label=f"last {period_days} days"),
        effect_size=EffectSize(value=slope, kind="slope_per_day", p_value=p_value),
        coverage=Coverage(
            is_sufficient=True,
            note=(
                f"cleared ≥{int(req['min_observations'])} observations over "
                f"≥{int(req['min_days'])} days"
            ),
        ),
        confidence=sd.get("confidence")
        if sd.get("confidence") in ("low", "medium", "high")
        else _p_confidence(p_value),
        limitations=["linear fit — a changepoint or plateau within the window is not modeled"],
        next_question=NextQuestion(
            prose=(
                f"Is this {_short(metric)} trend tied to a recent change "
                "worth pinning on your timeline?"
            )
        ),
    )


def _correlation_card(metric: str | None, sd: dict[str, Any]) -> FindingCard | None:
    metric_a = sd.get("metric_a")
    metric_b = sd.get("metric_b")
    coefficient = _num(sd.get("coefficient"))
    if not metric_a or not metric_b or coefficient is None:
        return None
    period_days = sd.get("period_days")
    p_value = _num(sd.get("p_value"))
    together = "inversely" if coefficient < 0 else "together"

    claim = (
        f"{_short(metric_a)} and {_short(metric_b)} moved {together} "
        f"(ρ={coefficient:.2f}) over {period_days} days"
    )

    verdict = readiness.classify_candidate(metric_a, metric_b)
    if verdict.verdict == readiness.TESTABLE:
        next_q = NextQuestion(
            prose=f"Worth an experiment — {verdict.suggested_protocol}",
            experiment_candidate=ExperimentCandidateRef(
                metric_a=metric_a,
                metric_b=metric_b,
                verdict=verdict.verdict,
                lever=verdict.lever,
                outcome=verdict.outcome,
                suggested_protocol=verdict.suggested_protocol,
                required_days=verdict.required_days,
            ),
        )
    else:
        next_q = NextQuestion(prose=verdict.rationale)

    return FindingCard(
        claim=claim,
        metric=metric or f"{metric_a}~{metric_b}",
        finding_type="correlation",
        current_window=WindowRef(
            label=f"last {period_days} days",
            n=int(period_days) if isinstance(period_days, int) else None,
        ),
        effect_size=EffectSize(
            value=coefficient,
            kind="spearman_rho",
            label=_rho_label(coefficient),
            p_value=p_value,
        ),
        confidence=_p_confidence(p_value),
        limitations=["correlation is not causation; same-day alignment only (no lag modeled yet)"],
        next_question=next_q,
    )


def _recovery_card(metric: str | None, sd: dict[str, Any]) -> FindingCard | None:
    score = _num(sd.get("score"))
    input_count = sd.get("input_count")
    input_total = sd.get("input_total")
    formula_version = sd.get("formula_version")
    missing = sd.get("missing_inputs") or []
    if (
        score is None
        or not isinstance(input_count, int)
        or not isinstance(input_total, int)
        or input_count < 3
        or input_total < input_count
        or formula_version != 2
    ):
        return None
    evidence_level = sd.get("evidence_level")
    return FindingCard(
        claim=f"Recovery score {score:.0f}",
        metric=metric or "recovery",
        finding_type="recovery_score",
        coverage=Coverage(
            is_sufficient=True,
            observation_count=input_count,
            note=f"{input_count} of {input_total} recovery inputs available",
        ),
        confidence="high" if evidence_level == "complete" else "medium",
        limitations=[f"{name} unavailable" for name in missing if isinstance(name, str)],
        next_question=NextQuestion(
            prose="Which input is moving recovery most — sleep, HRV, or resting heart rate?"
        ),
    )


def _summary_card(metric: str | None, sd: dict[str, Any]) -> FindingCard | None:
    if metric is None:
        return None
    avg = _num(sd.get("avg"))
    delta_pct = _num(sd.get("delta_pct_vs_baseline"))
    count = sd.get("count") or sd.get("sample_count")
    n = int(count) if isinstance(count, int) else None

    # A delta claim is only honest with enough samples behind it (see
    # _SUMMARY_DELTA_MIN_SAMPLES). Below the floor — or when the sample count is
    # unknown — we drop the delta and say so, instead of asserting a percentage
    # off one or two readings.
    delta_is_analyzable = (
        delta_pct is not None and n is not None and n >= _SUMMARY_DELTA_MIN_SAMPLES
    )

    if delta_is_analyzable:
        direction = "up" if delta_pct > 0 else "down" if delta_pct < 0 else "flat"
        # The aggregator baseline is (end − 30d → window_start), i.e. 30 − window
        # days long — the exact length isn't derivable from the builder's inputs,
        # so we say "recent baseline" rather than overstate it as "30-day".
        claim = f"{_short(metric)} ran {delta_pct:+.1f}% vs your recent baseline"
        delta = Delta(pct=delta_pct, direction=direction)
        baseline_window = WindowRef(label="recent baseline")
        coverage = Coverage(observation_count=n)
    elif avg is not None:
        claim = f"{_short(metric)} averaged {avg:.1f} over the period"
        delta = None
        baseline_window = None
        if delta_pct is not None:
            # A delta existed but too few samples to stand behind it — flag the
            # insufficiency explicitly rather than silently dropping it.
            samples = f"only {n} sample(s)" if n is not None else "an unknown sample count"
            coverage = Coverage(
                is_sufficient=False,
                observation_count=n,
                note=(
                    f"{samples} in window — delta vs your baseline not analyzable "
                    f"(needs ≥{_SUMMARY_DELTA_MIN_SAMPLES})"
                ),
            )
        else:
            coverage = Coverage(observation_count=n)
    else:
        return None

    return FindingCard(
        claim=claim,
        metric=metric,
        finding_type="summary",
        current_window=WindowRef(label="reporting period", n=n),
        baseline_window=baseline_window,
        delta=delta,
        coverage=coverage,
    )


def _parse_dt(value: Any):
    """Best-effort ISO → datetime (structured_data stores it as a string)."""
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


_BUILDERS = {
    "anomaly": lambda metric, sd, severity: _anomaly_card(metric, sd, severity),
    "trend": lambda metric, sd, severity: _trend_card(metric, sd),
    "correlation": lambda metric, sd, severity: _correlation_card(metric, sd),
    "recovery_score": lambda metric, sd, severity: _recovery_card(metric, sd),
    "summary": lambda metric, sd, severity: _summary_card(metric, sd),
}


def build_card(
    finding_type: str,
    metric: str | None,
    structured_data: dict[str, Any] | None,
    severity: str | None = None,
) -> FindingCard | None:
    """Build a :class:`FindingCard` for one finding, or ``None`` if it can't be described.

    Pure + deterministic. Unknown ``finding_type`` (or a finding too thin to fill
    ``claim`` honestly) returns ``None`` — the finding then persists with a
    ``NULL`` card and is served as ``schema_version 0``.
    """
    builder = _BUILDERS.get(finding_type)
    if builder is None:
        return None
    sd = structured_data if isinstance(structured_data, dict) else {}
    return builder(metric, sd, severity)


__all__ = ["build_card"]
