"""Pydantic response models for the ``/api/insights/*`` endpoints.

Every field is Optional (or a default-empty list) so the Phase 1 stub
routes can return empty shapes that validate cleanly. Real analysis
output will populate these the same way — no client-visible shape
change when Phase 1.5 lights up the statistical engine.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class FindingResponse(BaseModel):
    id: int | None = None
    finding_type: str | None = None
    metric: str | None = None
    severity: str | None = None
    structured_data: dict | None = None
    created_at: datetime | None = None


class AnomalyResponse(BaseModel):
    id: int | None = None
    metric: str | None = None
    severity: str | None = None
    magnitude: float | None = None
    direction: str | None = None
    detected_at: datetime | None = None
    context: dict | None = None


class TrendResponse(BaseModel):
    metric: str | None = None
    slope: float | None = None
    direction: str | None = None
    period_days: int | None = None
    p_value: float | None = None
    confidence: str | None = None


class DailyBriefingResponse(BaseModel):
    id: int | None = None
    date: str | None = None
    narrative: str | None = None
    findings: list[FindingResponse] = Field(default_factory=list)
    created_at: datetime | None = None


class WeeklySummaryResponse(BaseModel):
    id: int | None = None
    week_start: str | None = None
    week_end: str | None = None
    narrative: str | None = None
    findings: list[FindingResponse] = Field(default_factory=list)
    created_at: datetime | None = None


class InsightsLatestResponse(BaseModel):
    daily_briefing: DailyBriefingResponse | None = None
    weekly_summary: WeeklySummaryResponse | None = None
    recent_findings: list[FindingResponse] = Field(default_factory=list)


class AnomaliesListResponse(BaseModel):
    anomalies: list[AnomalyResponse] = Field(default_factory=list)
    count: int = 0


class TrendsListResponse(BaseModel):
    trends: list[TrendResponse] = Field(default_factory=list)
    count: int = 0


class TriggerRequest(BaseModel):
    type: str = "daily_briefing"


class TriggerResponse(BaseModel):
    status: str = "accepted"
    run_type: str | None = None
    message: str | None = None
    run_id: int | None = None
