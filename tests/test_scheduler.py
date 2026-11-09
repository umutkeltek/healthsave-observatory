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

        def add_job(self, func, trigger, *, id, max_instances, coalesce, kwargs=None):
            self.jobs.append(
                {
                    "func": func,
                    "trigger": trigger,
                    "id": id,
                    "max_instances": max_instances,
                    "coalesce": coalesce,
                    "kwargs": kwargs,
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


def test_scheduler_registers_correlation_analysis_when_explicitly_enabled(monkeypatch):
    fake_scheduler = _install_fake_apscheduler(monkeypatch)
    config = AnalysisConfig.model_validate(
        {"analysis": {"correlation_analysis": {"enabled": True, "cron": "0 10 1 * *"}}}
    )
    engine = type("Engine", (), {"run_correlation_analysis": AsyncMock()})()

    scheduler = AnalysisScheduler(engine, config)
    scheduler.start()

    instance = fake_scheduler.instances[0]
    assert instance.started is True
    assert len(instance.jobs) == 1
    assert instance.jobs[0]["id"] == "correlation_analysis"
    assert instance.jobs[0]["func"] == engine.run_correlation_analysis
    assert instance.jobs[0]["trigger"] == {"cron": "0 10 1 * *"}


def test_scheduler_registers_weekly_summary_when_explicitly_enabled(monkeypatch):
    fake_scheduler = _install_fake_apscheduler(monkeypatch)
    config = AnalysisConfig.model_validate(
        {"analysis": {"weekly_summary": {"enabled": True, "cron": "0 8 * * 1"}}}
    )
    engine = type("Engine", (), {"run_weekly_summary": AsyncMock()})()

    scheduler = AnalysisScheduler(engine, config)
    scheduler.start()

    instance = fake_scheduler.instances[0]
    assert instance.started is True
    assert len(instance.jobs) == 1
    assert instance.jobs[0]["id"] == "weekly_summary"
    assert instance.jobs[0]["func"] == engine.run_weekly_summary
    assert instance.jobs[0]["trigger"] == {"cron": "0 8 * * 1"}


def test_scheduler_registers_recovery_check_when_explicitly_enabled(monkeypatch):
    fake_scheduler = _install_fake_apscheduler(monkeypatch)
    config = AnalysisConfig.model_validate(
        {"analysis": {"recovery": {"enabled": True, "cron": "0 6 * * *"}}}
    )
    engine = type("Engine", (), {"run_recovery_check": AsyncMock()})()

    scheduler = AnalysisScheduler(engine, config)
    scheduler.start()

    instance = fake_scheduler.instances[0]
    assert instance.started is True
    assert len(instance.jobs) == 1
    assert instance.jobs[0]["id"] == "recovery_check"
    assert instance.jobs[0]["func"] == engine.run_recovery_check
    assert instance.jobs[0]["trigger"] == {"cron": "0 6 * * *"}


def test_scheduler_does_not_start_when_all_jobs_disabled(monkeypatch):
    fake_scheduler = _install_fake_apscheduler(monkeypatch)
    scheduler = AnalysisScheduler(type("Engine", (), {})(), AnalysisConfig())
    scheduler.start()
    # All jobs default-disabled → scheduler never constructed/started.
    assert fake_scheduler.instances == []
    assert scheduler.scheduler is None


def test_every_scheduled_job_skips_when_a_run_of_its_type_is_in_progress(monkeypatch):
    """Scheduled ticks are turned away by a run in progress (skip_if_busy);
    only trigger routes wait for it."""
    fake_scheduler = _install_fake_apscheduler(monkeypatch)
    config = AnalysisConfig.model_validate(
        {
            "analysis": {
                "daily_briefing": {"enabled": True},
                "anomaly_detection": {"enabled": True},
                "trend_analysis": {"enabled": True},
                "correlation_analysis": {"enabled": True},
                "weekly_summary": {"enabled": True},
                "recovery": {"enabled": True},
            }
        }
    )
    names = (
        "run_daily_briefing",
        "run_anomaly_check",
        "run_trend_analysis",
        "run_correlation_analysis",
        "run_weekly_summary",
        "run_recovery_check",
    )
    engine = type("Engine", (), {name: AsyncMock() for name in names})()
    AnalysisScheduler(engine, config).start()

    jobs = fake_scheduler.instances[0].jobs
    assert len(jobs) == 6
    assert all(job["kwargs"] == {"skip_if_busy": True} for job in jobs)
