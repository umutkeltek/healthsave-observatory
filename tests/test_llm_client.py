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


def _fake_response(
    content,
    prompt_tokens: int = 42,
    completion_tokens: int = 77,
    reasoning_content: str | None = None,
    finish_reason: str = "stop",
):
    """Build a LiteLLM-shaped response object for tests."""
    message = SimpleNamespace(content=content)
    if reasoning_content is not None:
        message.reasoning_content = reasoning_content
    choice = SimpleNamespace(message=message, finish_reason=finish_reason, index=0)
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
async def test_reasoning_model_falls_back_to_reasoning_content(monkeypatch):
    """GH #13: qwen3/R1-style endpoints put the output in ``reasoning_content``."""
    response = _fake_response("", reasoning_content="Your HRV is trending above baseline.")
    acompletion = AsyncMock(return_value=response)
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="qwen3:6b"))
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert "HRV is trending above baseline" in result.narrative
    assert "not medical advice" in result.narrative.lower()


@pytest.mark.asyncio
async def test_inline_think_block_is_stripped_from_content(monkeypatch):
    content = "<think>I should mention the baseline. Frame neutrally.</think>\n\nSleep was steady."
    acompletion = AsyncMock(return_value=_fake_response(content))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="qwen3:6b"))
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert result.narrative.startswith("Sleep was steady.")
    assert "<think>" not in result.narrative


@pytest.mark.asyncio
async def test_empty_narrative_is_a_failed_attempt_not_a_bare_disclaimer(monkeypatch):
    """An unclosed think block (truncated reasoning) yields no prose → the
    attempt fails so the chain can move on, instead of shipping the
    disclaimer alone as a 'successful' briefing."""
    acompletion = AsyncMock(return_value=_fake_response("<think>ran out of tokens"))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="qwen3:6b"))

    with pytest.raises(llm_client.LLMUnavailableError) as exc_info:
        await client.generate_insight("p", insight_type="daily_briefing")
    assert "empty narrative" in str(exc_info.value)


@pytest.mark.asyncio
async def test_empty_primary_narrative_falls_through_to_fallback(monkeypatch):
    """The empty-narrative failure participates in the candidate chain."""
    responses = [
        _fake_response(""),  # primary: reasoning model emitted nothing usable
        _fake_response("Recovery looks solid today."),
    ]
    acompletion = AsyncMock(side_effect=responses)
    _install_fake_litellm(monkeypatch, acompletion)

    config = LLMConfig(
        provider="ollama",
        model="qwen3:6b",
        fallback=[LLMFallbackEntry(provider="ollama", model="llama3.1:8b")],
    )
    client = llm_client.HealthLLMClient(config)
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert acompletion.await_count == 2
    assert "Recovery looks solid today." in result.narrative


@pytest.mark.asyncio
async def test_thinking_tag_variant_is_stripped(monkeypatch):
    content = "<thinking>frame it neutrally</thinking>HRV held steady."
    acompletion = AsyncMock(return_value=_fake_response(content))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="qwen3:6b"))
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert result.narrative.startswith("HRV held steady.")
    assert "<thinking>" not in result.narrative


@pytest.mark.asyncio
async def test_list_shaped_content_parts_are_joined(monkeypatch):
    """OpenAI-compatible servers may return content as typed parts, not a str."""
    content = [{"type": "text", "text": "Sleep was "}, {"type": "text", "text": "consistent."}]
    acompletion = AsyncMock(return_value=_fake_response(content))
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="qwen3:6b"))
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert result.narrative.startswith("Sleep was consistent.")


@pytest.mark.asyncio
async def test_response_with_no_choices_fails_over_not_crashes(monkeypatch):
    """A malformed provider response must feed the chain, not raise IndexError."""
    responses = [
        SimpleNamespace(choices=[], usage=None, model="ollama/qwen3:6b"),
        _fake_response("Recovery looks solid today."),
    ]
    acompletion = AsyncMock(side_effect=responses)
    _install_fake_litellm(monkeypatch, acompletion)

    config = LLMConfig(
        provider="ollama",
        model="qwen3:6b",
        fallback=[LLMFallbackEntry(provider="ollama", model="llama3.1:8b")],
    )
    client = llm_client.HealthLLMClient(config)
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert acompletion.await_count == 2
    assert "Recovery looks solid today." in result.narrative


@pytest.mark.asyncio
async def test_thinking_exhausted_budget_retries_same_model_with_boost(monkeypatch):
    """finish_reason=length + no prose → one boosted-budget retry, same candidate."""
    responses = [
        _fake_response("<think>still planning the narrative", finish_reason="length"),
        _fake_response(
            "<think>plan</think>Resting heart rate stayed near baseline.",
            prompt_tokens=42,
            completion_tokens=900,
        ),
    ]
    acompletion = AsyncMock(side_effect=responses)
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="qwen3:6b"))
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert acompletion.await_count == 2
    first, second = acompletion.await_args_list
    assert first.kwargs["max_tokens"] == 1000
    assert second.kwargs["max_tokens"] == 4000
    assert "Resting heart rate stayed near baseline." in result.narrative
    # Token accounting includes the burned first attempt
    assert result.tokens_out == 77 + 900


@pytest.mark.asyncio
async def test_boosted_retry_still_empty_fails_the_candidate(monkeypatch):
    acompletion = AsyncMock(
        return_value=_fake_response("<think>never stops thinking", finish_reason="length")
    )
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="qwen3:6b"))

    with pytest.raises(llm_client.LLMUnavailableError) as exc_info:
        await client.generate_insight("p", insight_type="daily_briefing")
    assert acompletion.await_count == 2  # one boost retry, not an endless loop
    assert "boosted-budget retry" in str(exc_info.value)


@pytest.mark.asyncio
async def test_truncated_but_nonempty_narrative_is_kept_without_retry(monkeypatch):
    """A narrative cut at the cap is still a narrative — warn, don't re-spend."""
    response = _fake_response("Sleep debt is accumulating and", finish_reason="length")
    acompletion = AsyncMock(return_value=response)
    _install_fake_litellm(monkeypatch, acompletion)

    client = llm_client.HealthLLMClient(LLMConfig(provider="ollama", model="llama3.1:8b"))
    result = await client.generate_insight("p", insight_type="daily_briefing")

    assert acompletion.await_count == 1
    assert "Sleep debt is accumulating" in result.narrative


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
