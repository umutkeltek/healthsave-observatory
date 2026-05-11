"""Agents service entrypoint — mirrors :mod:`worker.main`.

Loads the agents config block, validates against the discovered plugin
manifests under ``plugins/agents/``, builds a :class:`Supervisor`, and
runs it until SIGINT / SIGTERM.

The Compose service in ``docker-compose.yml`` invokes this via
``python -m agents.main`` on the same image as ``api`` / ``worker``.

Boundary note: ``apps/agents`` is allowed exactly one import from
``apps/api/server`` — :mod:`server.db.session` for the engine
bootstrap. The same precedent applies to :mod:`worker.main`. The
:mod:`tests.contract.test_apps_agents_boundary` test forbids anything
else (no route handlers, no ingestion code, no FastAPI internals).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from server.db.session import async_session, engine

from .config import UnknownAgentError, load_agents_config
from .supervisor import (
    EnabledAgent,
    ObservationFeed,
    Supervisor,
    build_enabled_agents,
)

log = logging.getLogger("agents.main")


def _default_observation_feed_factory(plugin_id: str) -> ObservationFeed:
    """Stub feed factory for Phase 7-C.

    Phase 7-D supplies a real factory that maps plugin ids to feed
    instances (e.g. ``hdh.agents.anomaly_watcher`` →
    ``AnalysisFindingsAnomalyFeed``). For now, raising here is the
    fail-loud signal: an operator enabled a real agent before the
    feed plumbing exists, and they need Phase 7-D before the
    supervisor can drive that plugin.
    """
    raise NotImplementedError(
        f"observation feed for plugin {plugin_id!r} is not configured yet; "
        "Phase 7-D wires concrete feeds (e.g. AnalysisFindingsAnomalyFeed)."
    )


async def run(
    *,
    config_path: Path | None = None,
    observation_feed_factory=_default_observation_feed_factory,
) -> None:
    """Build supervisor + wait for SIGTERM. Shared between CLI and tests."""
    config_path = config_path or Path(os.getenv("ANALYSIS_CONFIG", "/app/config.yaml"))
    try:
        agents_config = load_agents_config(config_path)
    except UnknownAgentError:
        # Fail loud — bad config should crash the service.
        raise

    resolved = agents_config.resolve()
    log.info(
        "agents service starting; enabled=%s",
        [s.plugin_id for s in resolved],
    )

    enabled: list[EnabledAgent] = []
    if resolved:
        enabled = build_enabled_agents(resolved, observation_feed_factory=observation_feed_factory)

    supervisor = Supervisor(
        session_factory=async_session,
        enabled=enabled,
    )

    await supervisor.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        log.info("agents service stopping")
        await supervisor.stop()
        await engine.dispose()


def main() -> None:
    """CLI entrypoint — ``python -m agents.main``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
