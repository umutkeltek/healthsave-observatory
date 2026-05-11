"""Agents config — parses the ``agents:`` block from ``config.yaml``.

Schema (snippet from ``config.yaml.example``)::

    agents:
      enabled: []                       # allowlist of plugin manifest ids
      defaults:
        tick_interval_seconds: 60
        timeout_seconds: 5
        restart_lookback_seconds: 3600
      plugins:
        hdh.agents.anomaly_watcher:     # per-plugin overrides
          tick_interval_seconds: 60

Discipline:

  * Empty default — no agent runs without an explicit ``enabled`` entry.
  * Fail-loud on unknown enabled ids — silent skip would let a typo
    masquerade as a working agent and create phantom safety.
  * Plugin identity is the manifest ``id``, not the folder slug. The
    config refers to plugins the same way :func:`plugin_sdk.load_plugin`
    addresses them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from plugin_sdk import DiscoveredPlugin, discover


class UnknownAgentError(RuntimeError):
    """An id listed in ``agents.enabled`` does not correspond to any
    discovered ``kind: agent`` plugin manifest. Fail-loud at startup —
    silent skip would hide typos and let an operator believe an agent
    is running when nothing is.
    """

    def __init__(self, unknown_id: str, known_ids: list[str]) -> None:
        super().__init__(
            f"agents.enabled references unknown plugin id {unknown_id!r}; "
            f"known agent plugin ids: {sorted(known_ids)!r}"
        )
        self.unknown_id = unknown_id
        self.known_ids = known_ids


@dataclass(frozen=True)
class AgentsDefaults:
    """Tick / timeout / restart-lookback defaults applied to every
    enabled agent unless overridden in ``agents.plugins.<id>``.
    """

    tick_interval_seconds: float = 60.0
    timeout_seconds: float = 5.0
    restart_lookback_seconds: float = 3600.0


@dataclass(frozen=True)
class AgentSettings:
    """Resolved per-agent settings — defaults merged with overrides."""

    plugin_id: str
    tick_interval_seconds: float
    timeout_seconds: float
    restart_lookback_seconds: float


@dataclass(frozen=True)
class AgentsConfig:
    """Top-level config — ``enabled`` + ``defaults`` + ``plugins``
    overrides. :meth:`resolve` produces the per-agent settings the
    supervisor consumes.
    """

    enabled: list[str] = field(default_factory=list)
    defaults: AgentsDefaults = field(default_factory=AgentsDefaults)
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def resolve(self) -> list[AgentSettings]:
        """Return per-agent settings, defaults merged with overrides.

        Order preserves ``enabled``'s ordering — the supervisor will
        schedule ticks in declaration order. No I/O; pure data.
        """
        resolved: list[AgentSettings] = []
        for plugin_id in self.enabled:
            override = self.overrides.get(plugin_id, {})
            resolved.append(
                AgentSettings(
                    plugin_id=plugin_id,
                    tick_interval_seconds=float(
                        override.get(
                            "tick_interval_seconds",
                            self.defaults.tick_interval_seconds,
                        )
                    ),
                    timeout_seconds=float(
                        override.get("timeout_seconds", self.defaults.timeout_seconds)
                    ),
                    restart_lookback_seconds=float(
                        override.get(
                            "restart_lookback_seconds",
                            self.defaults.restart_lookback_seconds,
                        )
                    ),
                )
            )
        return resolved


def _parse(raw: dict[str, Any]) -> AgentsConfig:
    block = raw.get("agents") or {}
    enabled = list(block.get("enabled") or [])
    defaults_block = block.get("defaults") or {}
    defaults = AgentsDefaults(
        tick_interval_seconds=float(
            defaults_block.get("tick_interval_seconds", AgentsDefaults.tick_interval_seconds)
        ),
        timeout_seconds=float(
            defaults_block.get("timeout_seconds", AgentsDefaults.timeout_seconds)
        ),
        restart_lookback_seconds=float(
            defaults_block.get("restart_lookback_seconds", AgentsDefaults.restart_lookback_seconds)
        ),
    )
    overrides = dict(block.get("plugins") or {})
    return AgentsConfig(enabled=enabled, defaults=defaults, overrides=overrides)


def load_agents_config(
    config_path: Path,
    *,
    plugins_dir: Path | None = None,
    discovered: list[DiscoveredPlugin] | None = None,
) -> AgentsConfig:
    """Read + parse ``config.yaml`` and validate against discovered plugins.

    Raises :class:`UnknownAgentError` if any id in ``agents.enabled`` is
    not present as a ``kind: agent`` plugin under ``plugins_dir``.

    ``discovered`` is an optional injection point for tests — when
    provided, skips the filesystem walk.
    """
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text()) or {}
    config = _parse(raw)

    if config.enabled:
        if discovered is None:
            discovered = discover(plugins_dir)
        known = [p.plugin_id for p in discovered if p.kind == "agent"]
        known_set = set(known)
        for enabled_id in config.enabled:
            if enabled_id not in known_set:
                raise UnknownAgentError(enabled_id, known)
    return config
