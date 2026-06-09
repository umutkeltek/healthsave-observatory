"""analysis.intelligence.resolve_llm_config — ADR-0003 D2 overlay resolver.

Pins the overlay semantics that make the narrator DB-configurable without a
redeploy, and the two safety invariants:

  * DB is an overlay, env is the floor: no settings / mode=off / a failing read
    all return the env ``base`` unchanged (the narrator never breaks on a
    missing settings table);
  * ``mode`` is the master switch: cloud egress is allowed only when
    mode='cloud' AND the opt-in is set — mode='local' forces it off.

The resolver lazily imports ``storage.timescale.intelligence``; tests stub that
module's read functions, so no DB is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from analysis.config import LLMConfig  # noqa: E402
from analysis.intelligence import resolve_llm_config  # noqa: E402
from storage.timescale import intelligence as repo_mod  # noqa: E402
from storage.timescale.intelligence import Connection, FallbackRoute, Settings  # noqa: E402

SESSION = object()  # opaque; the stubbed repo never touches it


def _settings(**over) -> Settings:
    base = dict(
        owner_id=repo_mod.DEFAULT_OWNER_ID,
        mode="cloud",
        primary_connection_id=1,
        primary_model="deepseek/deepseek-chat",
        primary_temperature=None,
        primary_max_tokens=None,
        primary_timeout_ms=None,
        allow_cloud_egress=True,
        redact_cloud_prompts=True,
        revision=1,
        consent_version=None,
        consent_text_hash=None,
        consented_at=None,
        consented_by=None,
    )
    base.update(over)
    return Settings(**base)


def _conn(**over) -> Connection:
    base = dict(
        id=1,
        provider="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com",
        destination="cloud",
        credential_id=10,
        enabled=True,
        last_test_status=None,
        last_test_at=None,
    )
    base.update(over)
    return Connection(**base)


def _install(
    monkeypatch,
    *,
    settings,
    connections=None,
    secret="sk-key",
    routes=None,
    settings_exc=None,
):
    """Stub the repo read functions the resolver calls."""
    conns = connections or {}

    async def get_settings(session, *, owner_id):
        if settings_exc is not None:
            raise settings_exc
        return settings

    async def get_connection(session, *, connection_id, owner_id):
        return conns.get(connection_id)

    async def get_connection_secret(session, *, connection_id, owner_id):
        return secret

    async def get_fallback_routes(session, *, owner_id):
        return routes or []

    monkeypatch.setattr(repo_mod, "get_settings", get_settings)
    monkeypatch.setattr(repo_mod, "get_connection", get_connection)
    monkeypatch.setattr(repo_mod, "get_connection_secret", get_connection_secret)
    monkeypatch.setattr(repo_mod, "get_fallback_routes", get_fallback_routes)


async def test_no_settings_returns_base_unchanged(monkeypatch):
    base = LLMConfig()
    _install(monkeypatch, settings=None)
    result = await resolve_llm_config(SESSION, base=base)
    assert result is base


async def test_mode_off_returns_base(monkeypatch):
    base = LLMConfig()
    _install(monkeypatch, settings=_settings(mode="off"))
    assert await resolve_llm_config(SESSION, base=base) is base


async def test_mode_on_but_no_primary_returns_base(monkeypatch):
    base = LLMConfig()
    _install(monkeypatch, settings=_settings(primary_connection_id=None))
    assert await resolve_llm_config(SESSION, base=base) is base


async def test_failing_settings_read_returns_base(monkeypatch):
    # The narrator must not break if the settings table is missing.
    base = LLMConfig()
    _install(monkeypatch, settings=None, settings_exc=RuntimeError("relation does not exist"))
    assert await resolve_llm_config(SESSION, base=base) is base


async def test_cloud_primary_overlays_provider_model_key_and_opt_in(monkeypatch):
    base = LLMConfig()  # ollama defaults, allow_cloud_egress False
    _install(monkeypatch, settings=_settings(), connections={1: _conn()}, secret="sk-live")
    result = await resolve_llm_config(SESSION, base=base)

    assert result is not base
    assert result.provider == "deepseek"
    assert result.model == "deepseek/deepseek-chat"
    assert result.base_url == "https://api.deepseek.com"
    assert result.api_key == "sk-live"
    assert result.allow_cloud_egress is True  # mode=cloud + opt-in
    assert result.redact_cloud_prompts is True


async def test_mode_local_forces_cloud_egress_off(monkeypatch):
    # Even with allow_cloud_egress True in the row, mode=local must not egress.
    base = LLMConfig()
    settings = _settings(mode="local", allow_cloud_egress=True, primary_model="llama3.1:8b")
    local_conn = _conn(provider="ollama", base_url="http://ollama:11434", credential_id=None)
    _install(monkeypatch, settings=settings, connections={1: local_conn})
    result = await resolve_llm_config(SESSION, base=base)

    assert result.provider == "ollama"
    assert result.allow_cloud_egress is False  # master switch
    assert result.api_key == ""  # no credential


async def test_cloud_opt_in_false_keeps_egress_off(monkeypatch):
    base = LLMConfig()
    _install(
        monkeypatch,
        settings=_settings(allow_cloud_egress=False),
        connections={1: _conn()},
    )
    result = await resolve_llm_config(SESSION, base=base)
    assert result.allow_cloud_egress is False


async def test_disabled_primary_connection_returns_base(monkeypatch):
    base = LLMConfig()
    _install(monkeypatch, settings=_settings(), connections={1: _conn(enabled=False)})
    assert await resolve_llm_config(SESSION, base=base) is base


async def test_primary_model_none_falls_back_to_base_model(monkeypatch):
    base = LLMConfig(model="env-default-model")
    _install(monkeypatch, settings=_settings(primary_model=None), connections={1: _conn()})
    result = await resolve_llm_config(SESSION, base=base)
    assert result.model == "env-default-model"


async def test_primary_temperature_and_max_tokens_overlay(monkeypatch):
    base = LLMConfig(temperature=0.3, max_tokens=1000)
    _install(
        monkeypatch,
        settings=_settings(primary_temperature=0.9, primary_max_tokens=256),
        connections={1: _conn()},
    )
    result = await resolve_llm_config(SESSION, base=base)
    assert result.temperature == 0.9
    assert result.max_tokens == 256


async def test_fallback_routes_become_self_describing_entries(monkeypatch):
    base = LLMConfig()
    routes = [
        FallbackRoute(
            id=1,
            priority=0,
            connection_id=2,
            model="openrouter/a:free",
            temperature=None,
            max_tokens=None,
            timeout_ms=None,
        ),
        FallbackRoute(
            id=2,
            priority=1,
            connection_id=3,
            model="openrouter/b:free",
            temperature=None,
            max_tokens=None,
            timeout_ms=None,
        ),
    ]
    connections = {
        1: _conn(),
        2: _conn(
            id=2, provider="openrouter", base_url="https://openrouter.ai/api/v1", credential_id=20
        ),
        3: _conn(
            id=3, provider="openrouter", base_url="https://openrouter.ai/api/v1", enabled=False
        ),
    }
    _install(
        monkeypatch, settings=_settings(), connections=connections, secret="or-key", routes=routes
    )
    result = await resolve_llm_config(SESSION, base=base)

    # Route 0 included with its connection's provider/base_url/key; route 1
    # skipped (its connection is disabled). Chain stays contiguous.
    assert len(result.fallback) == 1
    fb = result.fallback[0]
    assert fb.provider == "openrouter"
    assert fb.model == "openrouter/a:free"
    assert fb.base_url == "https://openrouter.ai/api/v1"
    assert fb.api_key == "or-key"
