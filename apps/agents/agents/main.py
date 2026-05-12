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
from collections.abc import Callable
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


class UnknownObservationFeedError(RuntimeError):
    """No feed factory is registered for the requested plugin id.

    Phase 7-D ships the anomaly-watcher feed; new agent plugins
    register here as they're added. Fail-loud — silent skip would let
    an operator believe an enabled agent is running when its
    observation feed is missing.
    """


def _build_default_feed_factory(session_factory) -> Callable[[str], ObservationFeed]:
    """Return a feed factory closed over the production session factory.

    Phase 7-D wires exactly one plugin: ``hdh.agents.anomaly_watcher``.
    New agent plugins extend this mapping as they ship — each plugin
    owns its feed module, the mapping just routes plugin id → feed
    instance.
    """
    # Local import — keeps plugin code off the import path for tests
    # that build their own factories.
    from plugins.agents.anomaly_watcher.feed import AnalysisFindingsAnomalyFeed

    feeds: dict[str, ObservationFeed] = {
        "hdh.agents.anomaly_watcher": AnalysisFindingsAnomalyFeed(session_factory=session_factory),
    }

    def factory(plugin_id: str) -> ObservationFeed:
        feed = feeds.get(plugin_id)
        if feed is None:
            raise UnknownObservationFeedError(
                f"no observation feed registered for plugin {plugin_id!r}; "
                "register one in agents.main._build_default_feed_factory()."
            )
        return feed

    return factory


async def run(
    *,
    config_path: Path | None = None,
    observation_feed_factory: Callable[[str], ObservationFeed] | None = None,
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

    if observation_feed_factory is None:
        observation_feed_factory = _build_default_feed_factory(async_session)

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
