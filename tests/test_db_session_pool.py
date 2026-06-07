"""PERFORMANCE-002: resilient DB connection-pool configuration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.db.session import _engine_kwargs  # noqa: E402


def test_engine_kwargs_enable_pool_resilience(monkeypatch):
    monkeypatch.delenv("DB_STATEMENT_TIMEOUT_MS", raising=False)
    kw = _engine_kwargs()
    assert kw["pool_pre_ping"] is True
    assert kw["pool_recycle"] > 0
    assert kw["pool_timeout"] > 0
    assert kw["pool_size"] >= 1
    # statement_timeout is opt-in: no connect_args by default.
    assert "connect_args" not in kw


def test_engine_kwargs_sets_statement_timeout_when_configured(monkeypatch):
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "30000")
    kw = _engine_kwargs()
    assert kw["connect_args"]["server_settings"]["statement_timeout"] == "30000"


def test_engine_kwargs_respect_pool_size_overrides(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "8")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "12")
    kw = _engine_kwargs()
    assert kw["pool_size"] == 8
    assert kw["max_overflow"] == 12
