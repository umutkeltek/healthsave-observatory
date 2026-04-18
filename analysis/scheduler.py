"""APScheduler-based cron for the analysis engine.

Phase 1.5 activation: a single ``daily_briefing`` job is registered when
``config.analysis.daily_briefing.enabled`` is true. APScheduler is
imported inside ``start()`` so module import stays cheap for pytest
collection (``AsyncIOScheduler()`` constructed at import time can fail
on Python 3.12+ when no event loop is running).
"""

from __future__ import annotations

import logging

log = logging.getLogger("healthsave.analysis")


class AnalysisScheduler:
    """Wrap an APScheduler instance that runs the analysis jobs.

    MVP registers only the daily-briefing job; the weekly / anomaly /
    trend / correlation jobs stay unregistered until Phase 2 lights up
    their engine methods. Future jobs follow the same pattern: check
    ``config.analysis.<job>.enabled``, then ``add_job`` with
    ``max_instances=1`` + ``coalesce=True`` to survive overlapping ticks.
    """

    def __init__(self, engine, config) -> None:
        """Store references; do NOT construct AsyncIOScheduler here yet."""
        self.engine = engine
        self.config = config
        self.scheduler = None

    def start(self) -> None:
        """Construct + start AsyncIOScheduler and register the daily briefing.

        No-ops (and logs) when ``daily_briefing.enabled`` is false so
        Docker users who want the API but not the scheduler can disable
        via ``config.yaml``.
        """
        if not self.config.analysis.daily_briefing.enabled:
            log.info("daily_briefing disabled in config; scheduler not starting")
            return

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self.engine.run_daily_briefing,
            CronTrigger.from_crontab(self.config.analysis.daily_briefing.cron),
            id="daily_briefing",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        log.info(
            "AnalysisScheduler started (daily_briefing cron=%s)",
            self.config.analysis.daily_briefing.cron,
        )

    def shutdown(self, wait: bool = False) -> None:
        """Gracefully shut down the scheduler on FastAPI lifespan exit."""
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=wait)
            self.scheduler = None
