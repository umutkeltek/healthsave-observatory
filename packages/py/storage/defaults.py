"""Production storage adapter selection.

Application routes import ports plus this module. Concrete TimescaleDB
repositories stay behind this seam so route modules can be tested with fakes
without importing adapter packages directly.
"""

from __future__ import annotations

from storage.ports import (
    AgentRepository,
    BriefingRepository,
    ExperimentRepository,
    ReadinessRepository,
    SyncReceiptRepository,
    TimeSeriesQueryService,
)
from storage.timescale.agents import default_repository as _agent_repository
from storage.timescale.analysis import default_readiness_repository as _readiness_repository
from storage.timescale.briefings import default_repository as _briefing_repository
from storage.timescale.experiments import default_repository as _experiment_repository
from storage.timescale.observations import CanonicalObservationRepository
from storage.timescale.sync_receipts import default_repository as _sync_receipt_repository

_time_series_query_service = CanonicalObservationRepository()


def agent_repository() -> AgentRepository:
    return _agent_repository


def briefing_repository() -> BriefingRepository:
    return _briefing_repository


def experiment_repository() -> ExperimentRepository:
    return _experiment_repository


def readiness_repository() -> ReadinessRepository:
    return _readiness_repository


def sync_receipt_repository() -> SyncReceiptRepository:
    return _sync_receipt_repository


def time_series_query_service() -> TimeSeriesQueryService:
    return _time_series_query_service


__all__ = [
    "agent_repository",
    "briefing_repository",
    "experiment_repository",
    "readiness_repository",
    "sync_receipt_repository",
    "time_series_query_service",
]
