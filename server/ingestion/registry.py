"""Pluggable storage backend registry.

The IngestStorage / AuditLog protocols define what a backend must do.
This module is the seam that lets operators choose *which* backend
runs without editing source — by name (env var), by config file, or
by plugging in a custom module that registers its own factory at
import time.

Built-in backends:
    postgres    — TimescaleDB via PostgresIngestStorage + PostgresAuditLog

Operators select a backend with the ``HDH_STORAGE_BACKEND`` env var
(default: ``postgres``). To ship a third-party backend, write a module
that calls :func:`register_backend` at import time, then point
``HDH_STORAGE_PLUGINS`` at it (comma-separated module paths). The
lifespan imports each plugin before reading the backend name, so a
plugin's registrations are live by the time the lookup happens.

Example custom backend module::

    # mycorp_health/influx_backend.py
    from server.ingestion.registry import register_backend

    def _influx_factory(config):
        from .influx_storage import InfluxIngestStorage
        return InfluxIngestStorage(config), None  # append-only, no audit log

    register_backend("influxdb", _influx_factory)

Then run with::

    HDH_STORAGE_PLUGINS=mycorp_health.influx_backend \\
    HDH_STORAGE_BACKEND=influxdb \\
    docker compose up
"""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Callable
from typing import Any

from .storage import (
    AuditLog,
    IngestStorage,
    PostgresAuditLog,
    PostgresIngestStorage,
)

log = logging.getLogger("healthsave.storage")

#: A factory takes a ``config`` mapping (may be empty) and returns the
#: storage + audit-log pair. ``audit_log`` may be ``None`` for
#: append-only backends.
StorageFactory = Callable[[dict[str, Any]], tuple[IngestStorage, AuditLog | None]]


_REGISTRY: dict[str, StorageFactory] = {}


def register_backend(name: str, factory: StorageFactory) -> None:
    """Register a backend factory under ``name`` (case-insensitive).

    Re-registering the same name overrides the previous factory; this
    is intentional so a custom plugin can supersede a built-in for
    testing.
    """
    _REGISTRY[name.lower()] = factory


def get_backend(
    name: str, config: dict[str, Any] | None = None
) -> tuple[IngestStorage, AuditLog | None]:
    """Instantiate the backend registered under ``name``.

    Raises :class:`ValueError` with a list of known backends when the
    name is unrecognised — the error message is the user-facing
    diagnostic for ops misconfiguration.
    """
    key = name.lower()
    factory = _REGISTRY.get(key)
    if factory is None:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise ValueError(
            f"unknown storage backend '{name}'. Registered backends: {known}. "
            f"Set HDH_STORAGE_PLUGINS to import a module that registers it."
        )
    return factory(config or {})


def registered_backends() -> list[str]:
    """Return the sorted list of registered backend names."""
    return sorted(_REGISTRY)


def load_plugins(plugin_modules: str | None) -> list[str]:
    """Import each comma-separated module in ``plugin_modules``.

    Each successful import is expected to call :func:`register_backend`
    at module level. Returns the list of modules that loaded
    successfully (in order). A failed import logs a warning but does
    not abort the lifespan — operators can still fall back to built-ins.
    """
    if not plugin_modules:
        return []
    loaded: list[str] = []
    for raw in plugin_modules.split(","):
        module_path = raw.strip()
        if not module_path:
            continue
        try:
            importlib.import_module(module_path)
        except ImportError as exc:
            log.warning("storage plugin import failed for %s: %s", module_path, exc)
            continue
        loaded.append(module_path)
        log.info("loaded storage plugin: %s", module_path)
    return loaded


def resolve_from_env() -> tuple[IngestStorage, AuditLog | None]:
    """One-shot helper used by the FastAPI lifespan.

    Reads ``HDH_STORAGE_PLUGINS`` and ``HDH_STORAGE_BACKEND`` from the
    process environment, loads any plugin modules, and returns the
    instantiated backend pair. Defaults to the built-in ``postgres``
    backend when no env vars are set.
    """
    load_plugins(os.environ.get("HDH_STORAGE_PLUGINS"))
    name = os.environ.get("HDH_STORAGE_BACKEND", "postgres")
    return get_backend(name)


# ── Built-in registrations ────────────────────────────────────────────


def _postgres_factory(_config: dict[str, Any]) -> tuple[IngestStorage, AuditLog | None]:
    """Default backend: TimescaleDB via the existing handlers."""
    return PostgresIngestStorage(), PostgresAuditLog()


register_backend("postgres", _postgres_factory)
