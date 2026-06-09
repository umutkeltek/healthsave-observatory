"""HealthLLMClient.healthcheck — test-connection probe (ADR-0003 D7).

Pins: the probe sends a one-token "ping" with NO health data; a local config
is allowed; a cloud config with a private-resolving base_url is refused as
SsrfError (distinct from a provider failure, which is ok=False). litellm is
mocked so no real call leaves.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from analysis.config import LLMConfig  # noqa: E402
from analysis.llm import client as llm_client  # noqa: E402
from analysis.llm.client import HealthcheckResult, HealthLLMClient  # noqa: E402
from analysis.netguard import SsrfError  # noqa: E402


def _install_fake_litellm(monkeypatch, acompletion):
    """Inject a fake ``litellm`` into sys.modules (it isn't installed in tests).

    Mirrors ``test_llm_client._install_fake_litellm``: the deferred
    ``import litellm`` inside the method resolves via ``sys.modules`` first.
    """
    fake = SimpleNamespace(acompletion=acompletion)
    monkeypatch.setitem(sys.modules, "litellm", fake)
    if hasattr(llm_client, "litellm"):
        monkeypatch.setattr(llm_client, "litellm", fake, raising=False)


@pytest.fixture
def captured(monkeypatch):
    """Fake litellm.acompletion that records the kwargs it was called with."""
    box: dict = {}

    async def fake_acompletion(**kwargs):
        box.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))])

    _install_fake_litellm(monkeypatch, fake_acompletion)
    return box


async def test_local_ollama_probe_ok(captured):
    client = HealthLLMClient(LLMConfig(provider="ollama", model="llama3.1:8b"))
    result = await client.healthcheck()

    assert isinstance(result, HealthcheckResult)
    assert result.ok is True
    assert result.destination == "local"
    assert result.model == "ollama/llama3.1:8b"
    assert result.latency_ms is not None


async def test_probe_sends_one_token_ping_no_health_data(captured):
    client = HealthLLMClient(LLMConfig(provider="ollama", model="m"))
    await client.healthcheck()

    assert captured["max_tokens"] == 1
    # fixed benign prompt — no health data, no findings, ever
    assert captured["messages"] == [{"role": "user", "content": "ping"}]


async def test_cloud_provider_default_endpoint_ok(captured):
    # No base_url → litellm's built-in endpoint; SSRF guard has nothing to check.
    client = HealthLLMClient(
        LLMConfig(provider="deepseek", model="deepseek/deepseek-chat", api_key="sk-x")
    )
    result = await client.healthcheck()

    assert result.ok is True
    assert result.destination == "cloud"
    assert captured["api_key"] == "sk-x"


async def test_provider_failure_is_not_ok(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("401 invalid api key")

    _install_fake_litellm(monkeypatch, boom)
    client = HealthLLMClient(LLMConfig(provider="deepseek", model="x", api_key="bad"))
    result = await client.healthcheck()

    assert result.ok is False
    assert "401" in result.error


async def test_cloud_base_url_to_private_ip_refused_as_ssrf(captured):
    # A "cloud" route pointing at an internal host must be refused BEFORE any call.
    client = HealthLLMClient(
        LLMConfig(provider="custom", model="x", base_url="https://sneaky.internal", api_key="k")
    )

    def resolver(host):
        return ["10.0.0.5"]

    with pytest.raises(SsrfError):
        await client.healthcheck(resolver=resolver)
    # and litellm was never called
    assert captured == {}
