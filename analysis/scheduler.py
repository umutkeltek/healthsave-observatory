"""APScheduler-based cron for the analysis engine.

Phase 2 registers two jobs when their respective config blocks are
enabled:

* ``daily_briefing`` — runs the full end-to-end path once a day.
* ``anomaly_check`` — runs the detector on a 30-minute cron, persists
  findings, no LLM call.

APScheduler is imported inside ``start()`` so module import stays cheap
for pytest collection (``AsyncIOScheduler()`` constructed at import time
can fail on Python 3.12+ when no event loop is running).
"""

from __future__ import annotations

import logging

log = logging.getLogger("healthsave.analysis")


class AnalysisScheduler:
    """Wrap an APScheduler instance that runs the analysis jobs.

    Every job follows the same pattern: check ``config.analysis.<job>.enabled``,
    then ``add_job`` with ``max_instances=1`` + ``coalesce=True`` to
    survive overlapping ticks.
    """

    def __init__(self, engine, config) -> None:
        """Store references; do NOT construct AsyncIOScheduler here yet."""
        self.engine = engine
        self.config = config
        self.scheduler = None

    def start(self) -> None:
        """Construct + start AsyncIOScheduler and register enabled jobs.

        No-ops (and logs) when neither ``daily_briefing`` nor
        ``anomaly_detection`` is enabled so Docker users who want the
        API but not the scheduler can disable both in ``config.yaml``.
        """
        daily = self.config.analysis.daily_briefing
        anomaly = self.config.analysis.anomaly_detection

        if not daily.enabled and not anomaly.enabled:
            log.info("daily_briefing and anomaly_detection both disabled; scheduler not starting")
            return

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        self.scheduler = AsyncIOScheduler()

        if daily.enabled:
            self.scheduler.add_job(
                self.engine.run_daily_briefing,
                CronTrigger.from_crontab(daily.cron),
                id="daily_briefing",
                max_instances=1,
                coalesce=True,
            )
            log.info("registered daily_briefing cron=%s", daily.cron)

        if anomaly.enabled:
            self.scheduler.add_job(
                self.engine.run_anomaly_check,
                CronTrigger.from_crontab(anomaly.cron),
                id="anomaly_check",
                max_instances=1,
                coalesce=True,
            )
            log.info("registered anomaly_check cron=%s", anomaly.cron)

        self.scheduler.start()
        log.info("AnalysisScheduler started")

    def shutdown(self, wait: bool = False) -> None:
        """Gracefully shut down the scheduler on FastAPI lifespan exit."""
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=wait)
            self.scheduler = None
