# SPDX-License-Identifier: Apache-2.0
"""UI surface primitives — what the web app reads, never raw SQL.

These are the contract between ``apps/api`` and ``apps/web``. The
dashboard never queries TimescaleDB directly; every chart and card
is composed of these typed responses, generated into TS via the
codegen pipeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ._base import V2Model, WithOwnership
from .narrative import NarrativeArtifact


class Annotation(V2Model):
    """A point or range marker on a chart — anomaly, intervention, event."""

    kind: Literal["point", "range"]
    at: datetime
    end: datetime | None = None
    text: str
    color: str | None = None


class SeriesResponse(WithOwnership):
    """Time-series data for a chart, plus annotations.

    ``points`` is ``(timestamp, value)`` pairs — typed as a list of
    two-element tuples so the TS codegen produces a sensible
    ``[string, number][]`` rather than an opaque object.
    """

    metric: str
    unit: str
    points: list[tuple[datetime, float]]
    annotations: list[Annotation] = []


class ChartSpec(V2Model):
    """Declarative chart spec — what to render, not how.

    The web app maps this to whichever chart library is current
    (Recharts/ECharts/Tremor); swapping the library is a ``apps/web``
    job, not a contract change.
    """

    metric: str
    chart_kind: Literal["line", "bar", "area", "scatter"]
    aggregation: Literal["raw", "hourly", "daily"] = "raw"
    range_days: int = Field(default=30, gt=0)
    annotations_enabled: bool = True


class NarrativeCard(V2Model):
    """A composed UI card — chart + briefing inline.

    The load-bearing primitive of the agent-platform UX: chart and
    its narrative ship in one HTTP/SSE response, not two requests.
    """

    chart: ChartSpec
    series: SeriesResponse | None = None
    narrative: NarrativeArtifact | None = None
