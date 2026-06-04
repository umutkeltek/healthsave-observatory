"""LiteLLM-based LLM client for the Brain-2 narrator.

Phase 1.5 activation: ``generate_insight`` now calls
``litellm.acompletion`` against the configured provider. The ``litellm``
package is imported lazily inside the method body so pytest collection
on Python 3.12/3.14 isn't slowed by the ~80MB LiteLLM import graph on
every touch of this module.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from ..egress import Destination, EgressPolicy, PayloadClass
from ..redaction import RedactionPolicy
from .prompts.base import SYSTEM_PROMPT
from .safety import inject_disclaimer

log = logging.getLogger("healthsave.analysis")


class LLMUnavailableError(RuntimeError):
    """Raised when the underlying LiteLLM call fails for any reason.

    Wraps connection errors, timeouts, and provider-side failures so the
    analysis engine can mark the run ``failed`` without leaking
    provider-specific exception types into the orchestration code.
    """


class InsightResult(BaseModel):
    """Structured narrator output.

    Captured separately from the raw LiteLLM response so the engine can
    persist narrative + token usage + the resolved model name (e.g.
    ``"ollama/llama3.1:8b"``) into ``analysis_insights`` and
    ``analysis_runs`` without carrying LiteLLM types through the stack.
    """

    narrative: str
    tokens_in: int
    tokens_out: int
    model: str
    insight_type: str


class HealthLLMClient:
    """Thin wrapper around LiteLLM with provider config + disclaimer enforcement."""

    # Approximate costs per 1K tokens (USD). Used for cost tracking.
    COST_TABLE: dict[str, float] = {
        "ollama": 0.0,
        "openai/gpt-4o-mini": 0.00015,
        "openai/gpt-4o": 0.005,
        "anthropic/claude-sonnet": 0.003,
        "anthropic/claude-opus": 0.015,
        "google/gemini-flash": 0.0001,
    }

    def __init__(self, config) -> None:
        """Store the :class:`~analysis.config.LLMConfig`; no LiteLLM calls here."""
        self.config = config
        self.egress_policy = EgressPolicy.from_config(config)
        self.redaction_policy = RedactionPolicy.from_llm_config(config)

    async def generate_insight(self, prompt: str, *, insight_type: str) -> InsightResult:
        """Generate a narrative from ``prompt`` and return an :class:`InsightResult`.

        The Ollama path prefixes the configured model with ``ollama/`` to
        produce e.g. ``"ollama/llama3.1:8b"`` as required by LiteLLM.
        Non-Ollama providers pass the model string through unchanged and
        rely on ``config.api_key`` / environment variables for auth.

        Any exception (timeout, connection error, provider error) is
        wrapped in :class:`LLMUnavailableError` so upstream callers only
        need to catch one type.

        Before any byte leaves the host, the egress policy (ADR-0001
        Decision G) is enforced fail-closed: a cloud provider without an
        explicit opt-in raises :class:`~analysis.egress.EgressDenied`. The
        prompt is derived data (aggregates / findings), classified
        ``PROMPT`` — raw observation rows are never sent here. For a cloud
        destination the prompt is additionally run through
        :class:`~analysis.redaction.RedactionPolicy` (on by default) to strip
        any residual identifiers; the local Ollama path is left untouched.
        """
        envelope = self.egress_policy.enforce(
            provider=self.config.provider, payload_class=PayloadClass.PROMPT
        )
        if envelope.destination is Destination.CLOUD:
            # Content scrub before the prompt crosses the trust boundary. The
            # local Ollama path is intentionally skipped — that data never left,
            # so there is nothing to strip and the local model gets full fidelity.
            if self.redaction_policy.enabled:
                redacted = self.redaction_policy.apply(prompt)
                if redacted.total:
                    log.info("egress redaction: scrubbed %s before cloud send", redacted.summary())
                prompt = redacted.text
            log.info(
                "egress: %s prompt → cloud provider %r (opted in)",
                envelope.payload_class.value,
                self.config.provider,
            )

        import litellm  # deferred import - keeps module-load light

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        if self.config.provider == "ollama":
            model = f"ollama/{self.config.model}"
        else:
            model = self.config.model

        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "timeout": 120,
        }
        if self.config.provider == "ollama":
            kwargs["api_base"] = self.config.base_url
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key

        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:  # noqa: BLE001 - intentional wrap-and-raise
            raise LLMUnavailableError(f"LLM call failed: {exc}") from exc

        raw = response.choices[0].message.content or ""
        narrative = inject_disclaimer(raw)
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

        return InsightResult(
            narrative=narrative,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=getattr(response, "model", model) or model,
            insight_type=insight_type,
        )

    async def track_usage(self, run_id: int, response) -> None:
        """Persist token counts and estimated cost to ``analysis_runs``.

        Token tracking in Phase 1.5 is folded into ``run_daily_briefing``
        directly (it already updates ``analysis_runs`` on completion), so
        this helper stays as a stub for future cross-provider accounting.
        """
        raise NotImplementedError(
            "Standalone usage tracking deferred; AnalysisEngine writes tokens inline."
        )
