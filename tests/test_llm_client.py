"""Unit tests for :class:`analysis.llm.client.HealthLLMClient`.

We monkeypatch the deferred ``litellm`` import inside
``analysis.llm.client`` so tests never actually load the ~80MB LiteLLM
package. ``unittest.mock.AsyncMock`` stands in for ``acompletion``
because ``MagicMock`` would fail on ``await``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analysis.llm.client as llm_client  # noqa: E402
from analysis.config import LLMConfig, LLMFallbackEntry  # noqa: E402
from analysis.egress import Destination, EgressDenied  # noqa: E402


def _fake_response(content: str, prompt_tokens: int = 42, completion_tokens: int = 77):
    """Build a LiteLLM-shaped response object for tests."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason="stop", index=0)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model="ollama/llama3.1:8b",
    )


def _install_fake_litellm(monkeypatch, acompletion_mock):
    """Inject a fake ``litellm`` module into ``sys.modules`` + client globals.

    Because the real ``import litellm`` lives inside the method body,
    Python resolves it via ``sys.modules`` first. Dropping a fake module
    there keeps us fully off the real LiteLLM import graph.
    """
    fake_litellm = SimpleNamespace(acompletion=acompletion_mock)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    # Some paths may have already imported via client module - set attribute too
    # so ``analysis.llm.client.litellm`` references the fake when it exists.
    if hasattr(llm_client, "litellm"):
        monkeypatch.setattr(llm_client, "litellm", fake_litellm, raising=False)


@pytest.mark.asyncio
async def test_generate_insight_calls_ollama_with_prefixed_model(monkeypatch):
    acompletion = AsyncMock(return_value=_fake_response("Everything looks normal."))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="llama3.1:8b"))

    result = await client.generate_insight("summary JSON here", insight_type="daily_briefing")

    assert acompletion.await_count == 1
    kwargs = acompletion.await_args.kwargs
    assert kwargs["model"] == "ollama/llama3.1:8b"
    assert kwargs["api_base"] == "http://ollama:11434"
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 1000
    assert kwargs["timeout"] == 120
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][1] == {"role": "user", "content": "summary JSON here"}

    assert result.tokens_in == 42
    assert result.tokens_out == 77
    assert result.insight_type == "daily_briefing"
    # Disclaimer appended when LLM omits it
    assert "not medical advice" in result.narrative.lower()


@pytest.mark.asyncio
async def test_generate_insight_preserves_existing_disclaimer(monkeypatch):
    content = "Your heart rate looks fine.\n\nThis is not medical advice. Please consult a doctor."
    acompletion = AsyncMock(return_value=_fake_response(content))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="llama3.1:8b"))
    result = await client.generate_insight("p", insight_type="daily_briefing")

    # Exactly one "not medical advice" - the existing one, not double-stamped
    assert result.narrative.lower().count("not medical advice") == 1


@pytest.mark.asyncio
async def test_generate_insight_wraps_failures_in_llm_unavailable_error(monkeypatch):
    acompletion = AsyncMock(side_effect=ConnectionError("ollama unreachable"))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="llama3.1:8b"))

    with pytest.raises(llm_client.LLMUnavailableError) as exc_info:
        await client.generate_insight("p", insight_type="daily_briefing")
    assert "ollama unreachable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_insight_denies_cloud_without_opt_in(monkeypatch):
    """Egress fail-closed: a cloud provider with no opt-in never calls out."""
    acompletion = AsyncMock(return_value=_fake_response("should not be reached"))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="openai", model="gpt-4o-mini"))

    with pytest.raises(EgressDenied) as exc_info:
        await client.generate_insight("derived findings", insight_type="daily_briefing")
    # The provider was never contacted — denial happens before any byte leaves.
    assert acompletion.await_count == 0
    assert exc_info.value.envelope.destination is Destination.CLOUD


@pytest.mark.asyncio
async def test_generate_insight_allows_cloud_when_opted_in(monkeypatch):
    acompletion = AsyncMock(return_value=_fake_response("Cloud narrative."))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(
        LLMConfig(provider="openai", model="gpt-4o-mini", allow_cloud_egress=True)
    )
    result = await client.generate_insight("derived findings", insight_type="daily_briefing")

    assert acompletion.await_count == 1
    # Non-ollama providers pass the model through unchanged (no ollama/ prefix).
    assert acompletion.await_args.kwargs["model"] == "gpt-4o-mini"
    assert "not medical advice" in result.narrative.lower()


@pytest.mark.asyncio
async def test_cloud_prompt_is_redacted_before_send(monkeypatch):
    """A cloud-bound prompt is scrubbed of identifiers before it leaves the host."""
    acompletion = AsyncMock(return_value=_fake_response("Cloud narrative."))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(
        LLMConfig(provider="openai", model="gpt-4o-mini", allow_cloud_egress=True)
    )
    await client.generate_insight(
        "owner contact jane.doe@example.com summary follows",
        insight_type="daily_briefing",
    )

    sent = acompletion.await_args.kwargs["messages"][1]["content"]
    assert "jane.doe@example.com" not in sent
    assert "[EMAIL]" in sent


@pytest.mark.asyncio
async def test_local_prompt_is_never_redacted(monkeypatch):
    """The local Ollama path keeps full fidelity — data never crossed the boundary."""
    acompletion = AsyncMock(return_value=_fake_response("Local narrative."))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="llama3.1:8b"))
    original = "owner contact jane.doe@example.com summary follows"
    await client.generate_insight(original, insight_type="daily_briefing")

    sent = acompletion.await_args.kwargs["messages"][1]["content"]
    assert sent == original  # untouched


@pytest.mark.asyncio
async def test_cloud_redaction_can_be_disabled(monkeypatch):
    """Opting out of redaction sends the raw prompt (explicit choice)."""
    acompletion = AsyncMock(return_value=_fake_response("Cloud narrative."))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(
        LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            allow_cloud_egress=True,
            redact_cloud_prompts=False,
        )
    )
    original = "contact jane.doe@example.com"
    await client.generate_insight(original, insight_type="daily_briefing")

    sent = acompletion.await_args.kwargs["messages"][1]["content"]
    assert sent == original


@pytest.mark.asyncio
async def test_fallback_used_when_primary_fails(monkeypatch):
    """Primary errors → the next candidate narrates; result comes from it."""
    acompletion = AsyncMock(
        side_effect=[ConnectionError("primary down"), _fake_response("Fallback narrative.")]
    )
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(
        LLMConfig(
            provider="ollama",
            model="llama3.1:8b",
            fallback=[LLMFallbackEntry(provider="ollama", model="llama3.2:3b")],
        )
    )
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert acompletion.await_count == 2  # primary tried, then fallback
    assert acompletion.await_args.kwargs["model"] == "ollama/llama3.2:3b"  # last = fallback
    assert "not medical advice" in result.narrative.lower()


@pytest.mark.asyncio
async def test_fallback_reruns_egress_gate_cloud_denied_then_local(monkeypatch):
    """Per-candidate egress check: a cloud primary with no opt-in is skipped
    (never contacted), and a *local* fallback narrates instead."""
    acompletion = AsyncMock(return_value=_fake_response("Local fallback narrative."))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(
        LLMConfig(
            provider="openai",  # cloud, no opt-in → egress-denied
            model="gpt-4o-mini",
            allow_cloud_egress=False,
            fallback=[LLMFallbackEntry(provider="ollama", model="llama3.2:3b")],
        )
    )
    result = await client.generate_insight("derived findings", insight_type="daily_briefing")

    # Cloud candidate was denied before any byte left; only the local one called out.
    assert acompletion.await_count == 1
    assert acompletion.await_args.kwargs["model"] == "ollama/llama3.2:3b"
    assert "not medical advice" in result.narrative.lower()


@pytest.mark.asyncio
async def test_all_cloud_no_opt_in_raises_egress_denied(monkeypatch):
    """If every candidate is egress-denied, the specific denial is surfaced
    (not a generic failure) and nothing ever leaves the host."""
    acompletion = AsyncMock(return_value=_fake_response("should not be reached"))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(
        LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            allow_cloud_egress=False,
            fallback=[LLMFallbackEntry(provider="anthropic", model="claude-3-5-sonnet")],
        )
    )
    with pytest.raises(EgressDenied) as exc_info:
        await client.generate_insight("derived findings", insight_type="daily_briefing")

    assert acompletion.await_count == 0
    assert exc_info.value.envelope.destination is Destination.CLOUD


def test_litellm_is_not_imported_at_module_scope():
    """Regression guard for ISC-A5 + D6: litellm must stay a deferred import.

    We grep the source file: no top-level ``import litellm`` statement. The
    import inside ``generate_insight`` body is fine and expected.
    """
    src = Path(llm_client.__file__).read_text()
    # Reject any occurrence of "import litellm" that is NOT indented
    # (module-level import would start at column 0).
    offending = [
        line
        for line in src.splitlines()
        if line.startswith("import litellm") or line.startswith("from litellm")
    ]
    assert offending == [], f"litellm imported at module scope: {offending}"
