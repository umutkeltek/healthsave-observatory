"""APScheduler-based cron for the analysis engine.

Phase 1 ships this class shape but does NOT construct
``AsyncIOScheduler`` at import time and does NOT start it from the
FastAPI lifespan. That wiring lands in Phase 1.5 once the engine
can actually produce findings.

Two design rules to preserve:

1. ``AsyncIOScheduler()`` is constructed inside ``__init__``, never at
   module import. Constructing it at import time causes pytest
   collection to fail on Python 3.12+ because no event loop is running.
2. The scheduler is not started by FastAPI ``lifespan`` in this round.
   ``server/main.py`` deliberately does not import this module.
"""


class AnalysisScheduler:
    """Wrap an APScheduler instance that runs the analysis jobs.

    Jobs:
      * daily briefing — default ``0 7 * * *``
      * weekly summary — default ``0 8 * * 1``
      * anomaly check — default ``*/30 * * * *``
      * trend analysis — default ``0 9 * * 1``
      * correlation analysis — default ``0 10 1 * *``

    Each job is registered conditionally based on the user's
    ``config.yaml`` (respecting the ``enabled`` flag).
    """

    def __init__(self, engine, config) -> None:
        """Store references; do NOT construct AsyncIOScheduler here yet."""
        self.engine = engine
        self.config = config
        self.scheduler = None  # AsyncIOScheduler() when wired in Phase 1.5

    def start(self) -> None:
        """Construct + start AsyncIOScheduler and register all enabled jobs."""
        raise NotImplementedError(
            "APScheduler wiring deferred to Phase 1.5 — apscheduler dep installed, not yet imported"
        )

    def shutdown(self, wait: bool = True) -> None:
        """Gracefully shut down the scheduler on FastAPI lifespan exit."""
        raise NotImplementedError(
            "APScheduler wiring deferred to Phase 1.5 — apscheduler dep installed, not yet imported"
        )
