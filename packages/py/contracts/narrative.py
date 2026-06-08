# SPDX-License-Identifier: Apache-2.0
"""Narrative primitives — LLM-generated content with structured evidence.

The v2 dashboard renders briefings token-by-token via SSE; the
persisted form lives here. Every claim has optional evidence
references and uncertainty so the UI can show "agent said X
because Y, with confidence Z."
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import V2Model, WithOwnership


class EvidenceRef(V2Model):
    """A pointer to a piece of evidence backing a claim."""

    kind: Literal["measurement", "finding", "observation", "external"]
    ref: str


class Uncertainty(V2Model):
    """How sure the narrator is about a claim."""

    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class Claim(V2Model):
    """One assertion inside a narrative, with optional evidence + uncertainty."""

    text: str
    evidence: list[EvidenceRef] = []
    uncertainty: Uncertainty | None = None


class Insight(V2Model):
    """A structured observation about the user's data.

    Severity matches the existing ``analysis.types.Severity`` literal so
    the v1 statistical engine output round-trips cleanly into v2 narratives.
    """

    metric: str | None = None
    severity: Literal["info", "watch", "alert"] = "info"
    summary: str
    claims: list[Claim] = []


class SuggestedAction(V2Model):
    """A user-visible suggestion. Defaults to requiring approval —
    suggestions are advisory, not auto-actuated."""

    text: str
    rationale: str | None = None
    requires_approval: bool = True


class NarrativeArtifact(WithOwnership):
    """A streamable narrative — daily briefing, weekly summary, etc.

    The wire shape is the *persisted* form. Streaming chunks go over
    SSE during render; once complete, the whole artifact is one row
    in this shape. The dashboard's ``BriefingCard`` reads this.
    """

    id: UUID
    kind: Literal[
        "daily_briefing",
        "weekly_summary",
        "anomaly_explanation",
        "intervention_proposal",
    ]
    rendered_at: datetime
    text: str
    insights: list[Insight] = []
    suggested_actions: list[SuggestedAction] = []
    narrator_plugin_id: str
    narrator_version: str
