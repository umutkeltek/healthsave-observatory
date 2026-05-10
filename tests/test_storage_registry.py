"""Storage backend registry behaviour."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.ingestion import registry  # noqa: E402
from server.ingestion.storage import (  # noqa: E402
    AuditLog,
    IngestStorage,
    PostgresAuditLog,
    PostgresIngestStorage,
)


@pytest.fixture
def isolated_registry():
    """Run each test against a snapshot of the registry, restoring on exit."""
    snapshot = dict(registry._REGISTRY)
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(snapshot)


def test_postgres_is_registered_by_default(isolated_registry):
    assert "postgres" in registry.registered_backends()


def test_get_postgres_backend_returns_protocol_compliant_pair(isolated_registry):
    storage, audit = registry.get_backend("postgres")
    assert isinstance(storage, PostgresIngestStorage)
    assert isinstance(audit, PostgresAuditLog)
    assert isinstance(storage, IngestStorage)
    assert isinstance(audit, AuditLog)


def test_backend_lookup_is_case_insensitive(isolated_registry):
    a, _ = registry.get_backend("postgres")
    b, _ = registry.get_backend("POSTGRES")
    c, _ = registry.get_backend("Postgres")
    assert type(a) is type(b) is type(c)


def test_unknown_backend_raises_with_helpful_message(isolated_registry):
    with pytest.raises(ValueError) as exc_info:
        registry.get_backend("clickhouse")

    msg = str(exc_info.value)
    assert "clickhouse" in msg
    assert "Registered backends" in msg
    assert "postgres" in msg
    assert "HDH_STORAGE_PLUGINS" in msg


def test_register_backend_adds_a_new_factory(isolated_registry):
    class StubStorage:
        async def get_or_create_device(self, session, device_type):
            return device_type

        async def ingest_metric(self, session, device_id, metric, samples, owner_id):
            return len(samples)

    def _factory(_config):
        return StubStorage(), None

    registry.register_backend("stub", _factory)
    assert "stub" in registry.registered_backends()

    storage, audit = registry.get_backend("stub")
    assert isinstance(storage, StubStorage)
    assert audit is None


def test_register_overwrites_existing_factory(isolated_registry):
    """Re-registering is intentionally allowed for testability."""

    class V1:
        async def get_or_create_device(self, session, device_type):
            return 1

        async def ingest_metric(self, session, device_id, metric, samples, owner_id):
            return 0

    class V2(V1):
        pass

    registry.register_backend("custom", lambda c: (V1(), None))
    registry.register_backend("custom", lambda c: (V2(), None))

    storage, _ = registry.get_backend("custom")
    assert isinstance(storage, V2)


def test_load_plugins_is_a_noop_when_unset(isolated_registry):
    assert registry.load_plugins(None) == []
    assert registry.load_plugins("") == []


def test_load_plugins_imports_each_module(isolated_registry):
    # The fake plugin module registers a stub backend at import time.
    fake_module_calls: list[str] = []

    class _FakeModule:
        def __init__(self, name):
            self.__name__ = name
            fake_module_calls.append(name)

    def fake_import(module_path):
        # Side-effect: register a backend named after the module.
        registry.register_backend(
            f"plugin-{module_path}",
            lambda _config: (PostgresIngestStorage(), None),
        )
        return _FakeModule(module_path)

    with patch.object(registry.importlib, "import_module", side_effect=fake_import):
        loaded = registry.load_plugins("foo.bar, baz.qux")

    assert loaded == ["foo.bar", "baz.qux"]
    assert "plugin-foo.bar" in registry.registered_backends()
    assert "plugin-baz.qux" in registry.registered_backends()


def test_load_plugins_logs_and_skips_failed_imports(isolated_registry, caplog):
    def fake_import(_module_path):
        raise ImportError("nope")

    with patch.object(registry.importlib, "import_module", side_effect=fake_import):
        loaded = registry.load_plugins("missing.module")

    assert loaded == []
    # Failure is non-fatal — server can still start with built-ins.


def test_resolve_from_env_defaults_to_postgres_when_unset(isolated_registry):
    with patch.dict("os.environ", {}, clear=False):
        # Pop the relevant vars in case they leaked from the dev shell.
        for key in ("HDH_STORAGE_BACKEND", "HDH_STORAGE_PLUGINS"):
            if key in __import__("os").environ:
                __import__("os").environ.pop(key)
        storage, audit = registry.resolve_from_env()

    assert isinstance(storage, PostgresIngestStorage)
    assert isinstance(audit, PostgresAuditLog)


def test_resolve_from_env_respects_backend_choice(isolated_registry):
    sentinel_calls: list[dict] = []

    class StubStorage:
        async def get_or_create_device(self, session, device_type):
            return device_type

        async def ingest_metric(self, session, device_id, metric, samples, owner_id):
            return 0

    def _factory(config):
        sentinel_calls.append(config)
        return StubStorage(), None

    registry.register_backend("sentinel", _factory)

    with patch.dict("os.environ", {"HDH_STORAGE_BACKEND": "sentinel"}, clear=False):
        storage, audit = registry.resolve_from_env()

    assert isinstance(storage, StubStorage)
    assert audit is None
    assert sentinel_calls == [{}]


def test_resolve_from_env_loads_plugins_before_lookup(isolated_registry, monkeypatch):
    """Order of operations: plugin imports must register before we look up."""
    import_order: list[str] = []

    def fake_import(module_path):
        import_order.append(f"import:{module_path}")
        # The plugin's import-time effect is to register a new backend.
        registry.register_backend(
            "via-plugin",
            lambda _config: (PostgresIngestStorage(), None),
        )

        class _M:
            __name__ = module_path

        return _M()

    monkeypatch.setenv("HDH_STORAGE_BACKEND", "via-plugin")
    monkeypatch.setenv("HDH_STORAGE_PLUGINS", "fake.plugin")
    monkeypatch.setattr(registry.importlib, "import_module", fake_import)

    storage, _ = registry.resolve_from_env()

    assert import_order == ["import:fake.plugin"]
    assert isinstance(storage, PostgresIngestStorage)
