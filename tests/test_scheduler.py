"""Tests for AnalysisScheduler job registration."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from analysis.scheduler import AnalysisScheduler  # noqa: E402


def _install_fake_apscheduler(monkeypatch):
    scheduler_module = ModuleType("apscheduler.schedulers.asyncio")
    trigger_module = ModuleType("apscheduler.triggers.cron")

    class FakeScheduler:
        instances = []

        def __init__(self):
            self.jobs = []
            self.started = False
            FakeScheduler.instances.append(self)

        def add_job(self, func, trigger, *, id, max_instances, coalesce):
            self.jobs.append(
                {
                    "func": func,
                    "trigger": trigger,
                    "id": id,
                    "max_instances": max_instances,
                    "coalesce": coalesce,
                }
            )

        def start(self):
            self.started = True

        def shutdown(self, wait=False):
            self.started = False

    class FakeCronTrigger:
        @classmethod
        def from_crontab(cls, cron):
            return {"cron": cron}

    scheduler_module.AsyncIOScheduler = FakeScheduler
    trigger_module.CronTrigger = FakeCronTrigger
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.asyncio", scheduler_module)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.cron", trigger_module)
    return FakeScheduler


def test_scheduler_registers_trend_analysis_when_explicitly_enabled(monkeypatch):
    fake_scheduler = _install_fake_apscheduler(monkeypatch)
    config = AnalysisConfig.model_validate(
        {"analysis": {"trend_analysis": {"enabled": True, "cron": "0 9 * * 1"}}}
    )
    engine = type("Engine", (), {"run_trend_analysis": AsyncMock()})()

    scheduler = AnalysisScheduler(engine, config)
    scheduler.start()

    instance = fake_scheduler.instances[0]
    assert instance.started is True
    assert len(instance.jobs) == 1
    assert instance.jobs[0]["id"] == "trend_analysis"
    assert instance.jobs[0]["func"] == engine.run_trend_analysis
    assert instance.jobs[0]["trigger"] == {"cron": "0 9 * * 1"}
