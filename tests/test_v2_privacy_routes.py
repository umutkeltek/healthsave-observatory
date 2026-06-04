"""Tests for GET /api/v2/privacy — the egress posture surface.

No DB. The route reads the in-process analysis config + the pure egress policy,
so each test builds an AnalysisConfig with a given llm block and asserts the
local-vs-cloud posture and the per-payload-class allow/deny breakdown.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from server.api.v2_privacy import privacy  # noqa: E402


def _request(llm: dict):
    config = AnalysisConfig.model_validate({"llm": llm})
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(analysis_config=config)))


def _by_class(result):
    return {entry["payload_class"]: entry for entry in result["egress"]}


@pytest.mark.asyncio
async def test_local_ollama_default_keeps_everything_on_host():
    result = await privacy(_request({"provider": "ollama"}))

    assert result["provider"] == "ollama"
    assert result["destination"] == "local"
    assert result["is_local"] is True
    assert result["cloud_active"] is False
    assert result["raw_observations_leave_host"] is False
    # Local destination is inside the boundary — nothing leaves the host.
    assert all(entry["leaves_host"] is False for entry in result["egress"])


@pytest.mark.asyncio
async def test_cloud_provider_without_optin_sends_nothing():
    result = await privacy(_request({"provider": "openai", "allow_cloud_egress": False}))

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
    result = await privacy(_request({"provider": "openai", "allow_cloud_egress": True}))

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
    on = await privacy(_request({"provider": "openai", "allow_cloud_egress": True}))
    assert on["cloud_prompt_redaction"] is True  # default-on

    off = await privacy(
        _request({"provider": "openai", "allow_cloud_egress": True, "redact_cloud_prompts": False})
    )
    assert off["cloud_prompt_redaction"] is False
