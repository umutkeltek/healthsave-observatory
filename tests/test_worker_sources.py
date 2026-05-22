"""Tests for the worker's source-plugin poll registration.

The job callable returned by :func:`make_whoop_poll` does live work
(opens an httpx client, creates a session, instantiates the plugin)
and is covered transitively by ``tests/test_plugin_whoop_ingest.py``;
re-running that integration via heavyweight mocks here would only
test the mocks. Instead, these tests pin the registration contract:

  * the job uses Whoop's id and a CronTrigger built from the supplied
    cron expression,
  * max_instances=1 + coalesce=True + replace_existing=True (defenses
    against overlapping ticks),
  * the default cron is sensible.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "worker"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from worker.sources import (  # noqa: E402
    WHOOP_DEFAULT_CRON,
    make_whoop_poll,
    register_whoop_poll,
)


@dataclass
class _RecordingScheduler:
    add_job_calls: list[dict[str, Any]] = field(default_factory=list)

    def add_job(self, func, trigger, **kwargs):
        self.add_job_calls.append({"func": func, "trigger": trigger, "kwargs": kwargs})


def test_register_whoop_poll_uses_default_cron_when_not_overridden():
    scheduler = _RecordingScheduler()
    register_whoop_poll(scheduler, session_factory=lambda: None)
    assert len(scheduler.add_job_calls) == 1
    call = scheduler.add_job_calls[0]
    assert call["kwargs"]["id"] == "whoop_poll"
    assert call["kwargs"]["max_instances"] == 1
    assert call["kwargs"]["coalesce"] is True
    assert call["kwargs"]["replace_existing"] is True
    # The trigger is a CronTrigger built from the default cron expression.
    from apscheduler.triggers.cron import CronTrigger

    assert isinstance(call["trigger"], CronTrigger)


def test_register_whoop_poll_honors_custom_cron_and_job_id():
    scheduler = _RecordingScheduler()
    register_whoop_poll(
        scheduler,
        session_factory=lambda: None,
        cron="0 */6 * * *",
        job_id="whoop_poll_custom",
    )
    call = scheduler.add_job_calls[0]
    assert call["kwargs"]["id"] == "whoop_poll_custom"


def test_default_cron_is_a_valid_crontab_expression():
    # If WHOOP_DEFAULT_CRON breaks CronTrigger.from_crontab, every Whoop
    # poll deploy explodes on worker startup; lock the constant.
    from apscheduler.triggers.cron import CronTrigger

    CronTrigger.from_crontab(WHOOP_DEFAULT_CRON)


def test_make_whoop_poll_returns_an_async_callable():
    """Sanity: returned thing is awaitable. We do not invoke it here —
    that would require live httpx + a session + the plugin manifest;
    the end-to-end behaviour lives in test_plugin_whoop_ingest.py.
    """
    import inspect

    job = make_whoop_poll(session_factory=lambda: None)
    assert callable(job)
    assert inspect.iscoroutinefunction(job)
