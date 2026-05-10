"""v1 Pydantic models — frozen wire shapes.

Re-exports for ergonomics. Direct imports from the submodules
(``compat_v1.models.batch``, ``compat_v1.models.insights``) work too;
the re-exports here let callers write
``from compat_v1.models import BatchPayload``.
"""

from .batch import BatchPayload
from .insights import (
    AnomaliesListResponse,
    AnomalyResponse,
    DailyBriefingResponse,
    FindingResponse,
    InsightsLatestResponse,
    RunsListResponse,
    RunSummaryResponse,
    TrendResponse,
    TrendsListResponse,
    TriggerRequest,
    TriggerResponse,
    WeeklySummaryResponse,
)

__all__ = [
    "BatchPayload",
    "AnomaliesListResponse",
    "AnomalyResponse",
    "DailyBriefingResponse",
    "FindingResponse",
    "InsightsLatestResponse",
    "RunsListResponse",
    "RunSummaryResponse",
    "TrendResponse",
    "TrendsListResponse",
    "TriggerRequest",
    "TriggerResponse",
    "WeeklySummaryResponse",
]
