"""Tests worker source-plugin poll registration.

The adapter-specific jobs should keep their public wrappers, but the runtime
poll lifecycle should have one shared seam so new source adapters do not copy
session/http/storage/commit/rollback boilerplate.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "worker"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from worker.sources import (  # noqa: E402
    AMAZFIT_DEFAULT_CRON,
    GOOGLE_HEALTH_DEFAULT_CRON,
    POLAR_DEFAULT_CRON,
    WHOOP_DEFAULT_CRON,
    SourcePollSpec,
    make_amazfit_poll,
    make_google_health_poll,
    make_polar_poll,
    make_source_poll,
    make_whoop_poll,
    register_amazfit_poll,
    register_google_health_poll,
    register_polar_poll,
    register_whoop_poll,
)


@dataclass
class _RecordingScheduler:
    add_job_calls: list[dict[str, Any]] = field(default_factory=list)

    def add_job(self, func, trigger, **kwargs):
        self.add_job_calls.append({"func": func, "trigger": trigger, "kwargs": kwargs})


def test_source_poll_helper_is_the_single_runtime_poll_seam() -> None:
    spec = SourcePollSpec(
        slug="polar",
        entrypoint="plugins.sources.polar:PolarSource",
        log_label="polar",
    )

    job = make_source_poll(session_factory=lambda: None, spec=spec)

    assert callable(job)
    assert inspect.iscoroutinefunction(job)


def test_all_source_poll_registrations_share_scheduler_contract() -> None:
    cases = [
        (register_whoop_poll, "whoop_poll"),
        (register_amazfit_poll, "amazfit_poll"),
        (register_polar_poll, "polar_poll"),
        (register_google_health_poll, "google_health_poll"),
    ]

    for register, expected_job_id in cases:
        scheduler = _RecordingScheduler()
        result = register(scheduler, session_factory=lambda: None)
        call = scheduler.add_job_calls[0]

        assert result == expected_job_id
        assert call["kwargs"]["id"] == expected_job_id
        assert call["kwargs"]["max_instances"] == 1
        assert call["kwargs"]["coalesce"] is True
        assert call["kwargs"]["replace_existing"] is True


def test_register_poll_honors_custom_cron_and_job_id() -> None:
    scheduler = _RecordingScheduler()

    register_polar_poll(
        scheduler,
        session_factory=lambda: None,
        cron="0 */6 * * *",
        job_id="polar_poll_custom",
    )

    call = scheduler.add_job_calls[0]
    assert call["kwargs"]["id"] == "polar_poll_custom"


def test_all_source_default_crons_are_valid_crontab_expressions() -> None:
    from apscheduler.triggers.cron import CronTrigger

    for cron in (
        WHOOP_DEFAULT_CRON,
        AMAZFIT_DEFAULT_CRON,
        POLAR_DEFAULT_CRON,
        GOOGLE_HEALTH_DEFAULT_CRON,
    ):
        CronTrigger.from_crontab(cron)


def test_all_source_poll_factories_return_async_callables() -> None:
    for factory in (
        make_whoop_poll,
        make_amazfit_poll,
        make_polar_poll,
        make_google_health_poll,
    ):
        job = factory(session_factory=lambda: None)
        assert callable(job)
        assert inspect.iscoroutinefunction(job)
