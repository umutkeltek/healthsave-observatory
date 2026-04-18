"""Pydantic models shared across the analysis engine.

This module has ZERO imports from ``server/`` so it can be imported
cheaply from routes, tests, or scripts without pulling in SQLAlchemy
or FastAPI.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Mirrors the CHECK constraints in migrations/002_analysis_tables.sql.
# Keep these enums in sync with the DB when either side changes.
Severity = Literal["info", "watch", "alert"]
RunStatus = Literal["running", "completed", "failed", "skipped"]
Direction = Literal["up", "down", "flat"]
Sensitivity = Literal["low", "normal", "high"]


class Finding(BaseModel):
    """One structured statistical finding produced by the Brain-1 engine."""

    finding_type: str
    metric: str | None = None
    severity: Severity = "info"
    structured_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class Insight(BaseModel):
    """A natural-language narrative produced by the Brain-2 narrator."""

    insight_type: str
    narrative: str
    findings_used: list[int] = Field(default_factory=list)
    created_at: datetime | None = None


class Anomaly(BaseModel):
    """A single deviation from baseline detected in a metric's time series."""

    metric: str
    magnitude: float
    direction: Direction
    severity: Severity = "info"
    detected_at: datetime | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class Trend(BaseModel):
    """A multi-day/multi-week trend detected via linear regression."""

    metric: str
    slope: float
    direction: Direction
    period_days: int
    p_value: float | None = None
    confidence: str | None = None


class Correlation(BaseModel):
    """A cross-metric correlation over a rolling window."""

    metric_a: str
    metric_b: str
    coefficient: float
    method: str = "spearman"
    period_days: int
    p_value: float | None = None


class PeriodSummary(BaseModel):
    """Aggregated metrics for a single analysis period (day/week/month)."""

    period: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    baseline_comparison: dict[str, dict[str, Any]] = Field(default_factory=dict)
    day_of_week_patterns: dict[str, Any] = Field(default_factory=dict)


class DataSummary(BaseModel):
    """Metadata about what data is available for a given analysis type."""

    metric: str | None = None
    observation_count: int = 0
    days_with_data: int = 0
    first_observation: datetime | None = None
    last_observation: datetime | None = None


class SufficiencyResult(BaseModel):
    """Output of :func:`analysis.statistical.gates.check_sufficiency`."""

    is_sufficient: bool
    missing_description: str | None = None
    days_until_sufficient: int | None = None
