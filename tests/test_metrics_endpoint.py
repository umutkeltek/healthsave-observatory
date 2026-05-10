"""Tests for Prometheus metrics exposure and instrumentation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from analysis.config import AnalysisConfig  # noqa: E402
from analysis.engine import AnalysisEngine  # noqa: E402
from server.api.deps import get_session  # noqa: E402
from server.api.metrics import (  # noqa: E402
    AI_BRIEFING_RUNS,
    INGEST_BATCHES,
    INGEST_DURATION,
    INGEST_ROWS,
    reset_metrics,
)

from tests.test_api_contract import FakeRequest, FakeSession  # noqa: E402


@pytest.fixture(autouse=True)
def reset_metric_state():
    reset_metrics()
    yield
    reset_metrics()


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def _histogram_count(histogram, **labels) -> float:
    target = {k: str(v) for k, v in labels.items()}
    suffix = f"{histogram._name}_count"
    for family in histogram.collect():
        for sample in family.samples:
            if sample.name == suffix and sample.labels == target:
                return sample.value
    return 0.0


def test_metrics_endpoint_returns_prometheus_text_with_expected_metric_names():
    with TestClient(server.app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    # prometheus_client returns "text/plain; version=...; charset=utf-8" — accept any version
    assert response.headers["content-type"].startswith("text/plain")
    assert "hdh_ingest_batches_total" in response.text
    assert "hdh_ingest_rows_total" in response.text
    assert "hdh_ai_briefing_runs_total" in response.text
    assert "hdh_ingest_duration_seconds" in response.text


def test_metrics_endpoint_returns_200_even_when_db_dependency_is_broken():
    async def broken_session():
        raise RuntimeError("database is unavailable")
        yield

    server.app.dependency_overrides[get_session] = broken_session
    try:
        with TestClient(server.app) as client:
            response = client.get("/metrics")
    finally:
        server.app.dependency_overrides.clear()

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingest_metrics_increment_for_processed_batch():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [
                {
                    "date": "2026-04-10T12:00:00+00:00",
                    "qty": 72,
                    "source": "Apple Watch",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    assert _counter_value(INGEST_BATCHES, metric="heart_rate") == 1
    assert _counter_value(INGEST_ROWS, metric="heart_rate") == 1
    assert _histogram_count(INGEST_DURATION, metric="heart_rate") == 1


@pytest.mark.asyncio
async def test_ingest_metrics_count_empty_batches_without_rows():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [],
        }
    )

    result = await server.apple_batch(request, session)

    assert result["status"] == "empty"
    assert _counter_value(INGEST_BATCHES, metric="heart_rate") == 1
    assert _counter_value(INGEST_ROWS, metric="heart_rate") == 0
    assert _histogram_count(INGEST_DURATION, metric="heart_rate") == 1


@pytest.mark.asyncio
async def test_validation_errors_do_not_increment_ingest_metrics():
    session = FakeSession()
    # samples must be a list[dict]; passing a string forces ValidationError → HTTP 422
    request = FakeRequest({"metric": "heart_rate", "samples": "not-a-list"})

    with pytest.raises(Exception) as exc_info:
        await server.apple_batch(request, session)

    assert getattr(exc_info.value, "status_code", None) == 422
    assert _counter_value(INGEST_BATCHES, metric="heart_rate") == 0
    assert _counter_value(INGEST_ROWS, metric="heart_rate") == 0
    assert _histogram_count(INGEST_DURATION, metric="heart_rate") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "job"),
    [
        ("run_daily_briefing", "daily_briefing"),
        ("run_anomaly_check", "anomaly_check"),
        ("run_trend_analysis", "trend_analysis"),
    ],
)
async def test_ai_briefing_metrics_count_none_returns_as_success(method_name: str, job: str):
    engine = AnalysisEngine(lambda: None, AsyncMock(), AnalysisConfig())
    impl_name = f"_{method_name}_impl"
    setattr(engine, impl_name, AsyncMock(return_value=None))

    result = await getattr(engine, method_name)()

    assert result is None
    assert _counter_value(AI_BRIEFING_RUNS, job=job, result="success") == 1
    assert _counter_value(AI_BRIEFING_RUNS, job=job, result="failure") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "job"),
    [
        ("run_daily_briefing", "daily_briefing"),
        ("run_anomaly_check", "anomaly_check"),
        ("run_trend_analysis", "trend_analysis"),
    ],
)
async def test_ai_briefing_metrics_count_failures_and_reraise(method_name: str, job: str):
    engine = AnalysisEngine(lambda: None, AsyncMock(), AnalysisConfig())
    impl_name = f"_{method_name}_impl"
    setattr(engine, impl_name, AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        await getattr(engine, method_name)()

    assert _counter_value(AI_BRIEFING_RUNS, job=job, result="success") == 0
    assert _counter_value(AI_BRIEFING_RUNS, job=job, result="failure") == 1
