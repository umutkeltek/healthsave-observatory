"""Tests for /api/insights route behavior."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from server.api.insights import insights_trigger  # noqa: E402
from server.models.insights import TriggerRequest  # noqa: E402


class _FakeEngine:
    def __init__(self, run_id: int | None):
        self.run_id = run_id
        self.calls = 0

    async def run_daily_briefing(self):
        self.calls += 1
        return self.run_id


def _request(*, enabled: bool, run_id: int | None = 123):
    config = AnalysisConfig.model_validate({"analysis": {"daily_briefing": {"enabled": enabled}}})
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=_FakeEngine(run_id),
            )
        )
    )


@pytest.mark.asyncio
async def test_trigger_accepts_missing_body_as_daily_briefing_default():
    request = _request(enabled=True, run_id=123)

    response = await insights_trigger(request)

    assert response.status == "completed"
    assert response.run_type == "daily_briefing"
    assert response.run_id == 123
    assert request.app.state.analysis_engine.calls == 1


@pytest.mark.asyncio
async def test_trigger_rejects_daily_briefing_when_analysis_is_disabled():
    request = _request(enabled=False)

    with pytest.raises(Exception) as exc_info:
        await insights_trigger(request, TriggerRequest(type="daily_briefing"))

    assert getattr(exc_info.value, "status_code", None) == 409
    assert request.app.state.analysis_engine.calls == 0
