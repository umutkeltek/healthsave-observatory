"""Experiment-readiness classifier — the n-of-1 on-ramp.

Given a cross-metric correlation candidate (already surfaced + ranked by
:mod:`analysis.statistical.correlations`), decide whether it can become a
controlled n-of-1 experiment: which metric is the behavioral *lever* the user
can manipulate, which is the *outcome* to measure, and a suggested ABAB protocol
skeleton.

This is the light on-ramp the product roadmap calls for — it deliberately stops
short of the full experiment engine: no ``ExperimentRepository``, no phase
scheduling, no significance testing. It only answers "is this worth turning into
an experiment, and what would that experiment look like?" so the dashboard can
rank candidates as actions. Pure: no DB, no HTTP, no LLM — classifies from the
metric ids alone, so it unit-tests without the ontology or a database.

Lever vs outcome is a naming-convention heuristic over ``metric_id`` prefixes
rather than an ontology lookup, keeping the module dependency-free: ``activity.``
/ ``nutrition.`` / ``mindfulness.`` (and a couple of explicit behaviors) are
things you *do*; everything else (vitals, cardio, metabolic, body, sleep stages)
is a physiological *response* you measure.
"""

from __future__ import annotations

from dataclasses import dataclass

# metric_id prefixes that denote a behavior the user can directly change — the
# experiment "lever". Everything not matched is treated as an outcome.
_LEVER_PREFIXES: tuple[str, ...] = ("activity.", "nutrition.", "mindfulness.")
_LEVER_METRIC_IDS: frozenset[str] = frozenset(
    {
        "sleep.duration",  # partly controllable (bedtime), unlike sleep stages
        "environment.time_in_daylight",
    }
)

# A minimal ABAB run: two baseline (A) + two intervention (B) blocks. One week
# per block is the conventional floor for daily biometrics to average out noise.
_BLOCK_DAYS = 7
_BLOCKS = 4
_MIN_EXPERIMENT_DAYS = _BLOCK_DAYS * _BLOCKS  # 28

# Verdicts. Kept as plain strings (not an enum) so the wire shape is obvious and
# the set can grow (e.g. "needs_more_data" once live baseline coverage is wired).
TESTABLE = "testable"
NOT_CONTROLLABLE = "not_controllable"


@dataclass(frozen=True)
class ReadinessVerdict:
    """Whether a correlation candidate can become an n-of-1 experiment."""

    verdict: str
    lever: str | None
    outcome: str | None
    suggested_protocol: str | None
    required_days: int | None
    rationale: str


def _is_lever(metric_id: str) -> bool:
    return metric_id in _LEVER_METRIC_IDS or metric_id.startswith(_LEVER_PREFIXES)


def _short(metric_id: str) -> str:
    """Human-readable tail of a metric id: ``vital.resting_heart_rate`` → ``resting heart rate``."""
    return metric_id.rsplit(".", 1)[-1].replace("_", " ")


def classify_candidate(metric_a: str, metric_b: str) -> ReadinessVerdict:
    """Classify a correlation pair into an experiment-readiness verdict.

    Order-independent: whichever side is the behavioral lever becomes the thing
    you manipulate, the other the outcome you measure. A pair where both sides
    are behaviors (mechanically coupled, e.g. steps ↔ active energy) or both are
    physiological outcomes (e.g. HRV ↔ resting HR) has no independent knob to
    turn, so it is ``not_controllable``.
    """
    a_lever = _is_lever(metric_a)
    b_lever = _is_lever(metric_b)

    if a_lever == b_lever:
        if a_lever:
            rationale = (
                "both metrics are behaviors you control directly — there's no "
                "independent outcome to measure the change against."
            )
        else:
            rationale = (
                "both metrics are physiological outcomes — neither is a behavior "
                "you can set directly to run an experiment."
            )
        return ReadinessVerdict(
            verdict=NOT_CONTROLLABLE,
            lever=None,
            outcome=None,
            suggested_protocol=None,
            required_days=None,
            rationale=rationale,
        )

    lever = metric_a if a_lever else metric_b
    outcome = metric_b if a_lever else metric_a
    protocol = (
        f"Alternate ~{_BLOCK_DAYS} days of higher {_short(lever)} with ~{_BLOCK_DAYS} days at your "
        f"usual level (ABAB, {_BLOCKS} blocks), measuring {_short(outcome)}."
    )
    rationale = (
        f"{_short(lever)} is a behavior you can change — measure its effect on {_short(outcome)}."
    )
    return ReadinessVerdict(
        verdict=TESTABLE,
        lever=lever,
        outcome=outcome,
        suggested_protocol=protocol,
        required_days=_MIN_EXPERIMENT_DAYS,
        rationale=rationale,
    )
