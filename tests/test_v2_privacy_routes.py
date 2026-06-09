"""Tests for GET /api/v2/privacy — the egress posture surface.

The route now reports the *effective* posture: the env analysis config overlaid
with DB Intelligence settings via ``resolve_llm_config``. These tests stub that
resolver to identity (return the env base) so the posture-logic cases stay
DB-free and focused on the egress policy; a final case stubs it to a cloud
overlay to prove the DB settings flow through to the chip.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig, LLMConfig  # noqa: E402
from server.api import v2_privacy  # noqa: E402
from server.api.v2_privacy import privacy  # noqa: E402

_SESSION = object()  # opaque; the stubbed resolver never touches it


@pytest.fixture(autouse=True)
def _identity_resolver(monkeypatch):
    """Default: resolver returns the env base unchanged (DB-free posture tests)."""

    async def identity(session, *, base, owner_id=None):
        return base

    monkeypatch.setattr(v2_privacy, "resolve_llm_config", identity)


def _request(llm: dict):
    config = AnalysisConfig.model_validate({"llm": llm})
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(analysis_config=config)))


def _by_class(result):
    return {entry["payload_class"]: entry for entry in result["egress"]}


@pytest.mark.asyncio
async def test_local_ollama_default_keeps_everything_on_host():
    result = await privacy(_request({"provider": "ollama"}), session=_SESSION)

    assert result["provider"] == "ollama"
    assert result["destination"] == "local"
    assert result["is_local"] is True
    assert result["cloud_active"] is False
    assert result["raw_observations_leave_host"] is False
    # Local destination is inside the boundary — nothing leaves the host.
    assert all(entry["leaves_host"] is False for entry in result["egress"])


@pytest.mark.asyncio
async def test_cloud_provider_without_optin_sends_nothing():
    result = await privacy(
        _request({"provider": "openai", "allow_cloud_egress": False}), session=_SESSION
    )

    assert result["is_local"] is False
    assert result["allow_cloud_egress"] is False
    assert result["cloud_active"] is False  # configured but not opted in
    assert result["raw_observations_leave_host"] is False
    classes = _by_class(result)
    # Cloud not enabled → even derived payloads are denied (and don't leave).
    assert classes["findings"]["allowed"] is False
    assert classes["findings"]["leaves_host"] is False


@pytest.mark.asyncio
async def test_cloud_optin_lets_derived_leave_but_never_raw():
    result = await privacy(
        _request({"provider": "openai", "allow_cloud_egress": True}), session=_SESSION
    )

    assert result["is_local"] is False
    assert result["cloud_active"] is True
    assert result["raw_observations_leave_host"] is False  # invariant

    classes = _by_class(result)
    assert classes["raw_observations"]["allowed"] is False
    assert classes["raw_observations"]["leaves_host"] is False
    for derived in ("findings", "aggregates", "evidence", "prompt"):
        assert classes[derived]["allowed"] is True
        assert classes[derived]["leaves_host"] is True


@pytest.mark.asyncio
async def test_posture_reports_cloud_prompt_redaction():
    on = await privacy(
        _request({"provider": "openai", "allow_cloud_egress": True}), session=_SESSION
    )
    assert on["cloud_prompt_redaction"] is True  # default-on

    off = await privacy(
        _request({"provider": "openai", "allow_cloud_egress": True, "redact_cloud_prompts": False}),
        session=_SESSION,
    )
    assert off["cloud_prompt_redaction"] is False


@pytest.mark.asyncio
async def test_db_overlay_flows_through_to_the_chip(monkeypatch):
    """Even with an Ollama env floor, a DB cloud overlay makes the chip cloud-active.

    Proves /api/v2/privacy reports what the narrator will actually do (the
    resolved config), not just the boot-time env.
    """

    async def cloud_overlay(session, *, base, owner_id=None):
        return LLMConfig(
            provider="deepseek", model="deepseek/deepseek-chat", allow_cloud_egress=True
        )

    monkeypatch.setattr(v2_privacy, "resolve_llm_config", cloud_overlay)

    # Env floor is local Ollama, but the DB overlay is opted-in cloud.
    result = await privacy(_request({"provider": "ollama"}), session=_SESSION)

    assert result["provider"] == "deepseek"
    assert result["is_local"] is False
    assert result["cloud_active"] is True
    assert result["raw_observations_leave_host"] is False  # invariant holds
