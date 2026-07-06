# SPDX-License-Identifier: Apache-2.0
"""The Finding Card — the product's content model for "what changed, with evidence".

A :class:`FindingCard` is the versioned, wire-stable projection of one
structured statistical finding (anomaly / trend / correlation / recovery /
summary) into the ONE grammar the whole product speaks: web, the weekly Body
Brief, and the agent/MCP surface all render this exact shape. It is **computed
content** — every field is filled deterministically by the Brain-1 statistical
producers from math they already do (``analysis/statistical/finding_cards.py``).
The LLM narrator never fills a card field; it only narrates finished cards.

The fields track the R4 spec: ``claim`` / ``metric`` / ``current_window`` /
``baseline_window`` / ``delta`` / ``effect_size`` / ``coverage`` / ``sources`` /
``confidence`` / ``limitations`` / ``confounders`` / ``next_question``. The
``next_question`` is the flywheel — it carries both prose and an optional machine
hook (:class:`ExperimentCandidateRef`) that speaks the SAME vocabulary as
``/api/v2/experiments/candidates`` (metric pair → lever / outcome / suggested
protocol), so a finding can be promoted into an n-of-1 experiment with one click.

Versioning & backfill story
---------------------------
``schema_version`` is a monotonic integer describing the card grammar, NOT the
finding's data:

* **0** — a *legacy* finding persisted before this schema existed. Its
  ``analysis_findings.card`` column is ``NULL``; the read API serves
  ``{"card": null, "schema_version": 0}``. Legacy findings are represented
  honestly (no fabricated fields), never destructively rewritten.
* **1** (:data:`FINDING_CARD_SCHEMA_VERSION`, current) — a card built by the
  current producers, persisted as JSONB in ``analysis_findings.card``.

Every field except ``claim`` / ``metric`` / ``schema_version`` is optional so a
thin finding (or a future migrated legacy one) can be represented without
inventing data. A future card revision (v2) bumps this constant, adds/renames
fields additively, and readers switch on ``schema_version``. A backfill job (not
built here — intentionally deferred) would re-run the pure builders over historic
``analysis_findings.structured_data`` rows to populate ``card`` for old findings;
because the builders are pure and deterministic, that backfill is replayable and
side-effect-free. Until then, old rows coexist as ``schema_version 0`` forever —
no coordinated upgrade required for a self-hoster.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ._base import V2Model

# Current card grammar version. Legacy findings (no card column) are version 0.
FINDING_CARD_SCHEMA_VERSION = 1

CardDirection = Literal["up", "down", "flat"]
CardConfidence = Literal["low", "medium", "high"]


class WindowRef(V2Model):
    """A time window a finding is measured over (current or baseline)."""

    label: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    # Days (or samples) of data that fell inside the window — the "n".
    n: int | None = None


class Delta(V2Model):
    """The change: current vs baseline."""

    absolute: float | None = None
    pct: float | None = None
    unit: str | None = None
    direction: CardDirection | None = None


class EffectSize(V2Model):
    """How big the effect is, method-tagged so the UI can label it honestly.

    ``kind`` names the statistic (``z_score`` / ``spearman_rho`` /
    ``slope_per_day`` / ``cohens_d`` …) so a reader never confuses a correlation
    coefficient with a standardized mean difference. ``p_value`` rides alongside
    the magnitude (significance ≠ size) rather than being a separate top-level
    card field.
    """

    value: float | None = None
    kind: str | None = None
    label: str | None = None
    p_value: float | None = None


class Coverage(V2Model):
    """Data sufficiency behind the finding — the ``gates.py`` verdict, surfaced.

    A finding is only emitted once its producer's sufficiency gate passed, so
    ``is_sufficient`` is typically ``True``; ``note`` records the threshold that
    was cleared (e.g. "≥14 observations over ≥7 days"). ``days_until_sufficient``
    is only meaningful on the not-yet-analyzable path a future producer might
    surface.
    """

    is_sufficient: bool | None = None
    observation_count: int | None = None
    days_with_data: int | None = None
    days_until_sufficient: int | None = None
    note: str | None = None


class SourceRef(V2Model):
    """Where the underlying data came from (provenance, at card granularity)."""

    source_plugin_id: str | None = None
    label: str | None = None


class Confounder(V2Model):
    """A competing explanation the engine already accounts for or flags.

    Mirrors the context-suppression rules in the detectors (workout-window HR
    spikes, post-workout HRV drops, the sleep window) so a card can say *why* a
    reading might not mean what it looks like.
    """

    kind: str
    description: str
    metric: str | None = None


class ExperimentCandidateRef(V2Model):
    """Machine hook linking ``next_question`` to the experiments surface.

    Deliberately speaks the ``/api/v2/experiments/candidates`` vocabulary
    (metric pair + lever/outcome/verdict/protocol from the readiness classifier)
    — the candidate shape the experiment engine already ranks, so nothing new is
    invented here. The ``POST /api/v2/experiments`` create body renames the pair
    to ``lever_metric_id`` / ``outcome_metric_id``: the values are identical, only
    the field names differ, so the client maps ``lever`` → ``lever_metric_id`` and
    ``outcome`` → ``outcome_metric_id`` when promoting a candidate.
    """

    metric_a: str
    metric_b: str
    verdict: str | None = None
    lever: str | None = None
    outcome: str | None = None
    suggested_protocol: str | None = None
    required_days: int | None = None


class NextQuestion(V2Model):
    """The flywheel field: prose + an optional promotable experiment candidate."""

    prose: str
    experiment_candidate: ExperimentCandidateRef | None = None


class FindingCard(V2Model):
    """The versioned content model for one evidence-linked finding.

    ``claim`` / ``metric`` / ``schema_version`` are required; everything else is
    optional so legacy or thin findings are represented without fabrication.
    """

    schema_version: int = FINDING_CARD_SCHEMA_VERSION
    claim: str
    metric: str
    finding_type: str | None = None
    current_window: WindowRef | None = None
    baseline_window: WindowRef | None = None
    delta: Delta | None = None
    effect_size: EffectSize | None = None
    coverage: Coverage | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: CardConfidence | None = None
    limitations: list[str] = Field(default_factory=list)
    confounders: list[Confounder] = Field(default_factory=list)
    next_question: NextQuestion | None = None


__all__ = [
    "FINDING_CARD_SCHEMA_VERSION",
    "CardConfidence",
    "CardDirection",
    "WindowRef",
    "Delta",
    "EffectSize",
    "Coverage",
    "SourceRef",
    "Confounder",
    "ExperimentCandidateRef",
    "NextQuestion",
    "FindingCard",
]
