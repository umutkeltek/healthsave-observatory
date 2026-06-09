"""LiteLLM-based LLM client for the Brain-2 narrator.

Phase 1.5 activation: ``generate_insight`` now calls
``litellm.acompletion`` against the configured provider. The ``litellm``
package is imported lazily inside the method body so pytest collection
on Python 3.12/3.14 isn't slowed by the ~80MB LiteLLM import graph on
every touch of this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel

from ..egress import Destination, EgressDenied, EgressGate, EgressPolicy, EgressRoute, PayloadClass
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


@dataclass(frozen=True)
class _Candidate:
    """One narrator attempt: a provider + model (+ optional auth) to try.

    The chain is ``[primary, *fallback]``. ``model`` is the bare tag for Ollama
    (the ``ollama/`` prefix is re-added at call time) and the full litellm route
    for cloud providers. Each candidate is re-checked against the egress gate
    before any byte leaves, so a cloud fallback still needs the opt-in.
    """

    provider: str
    model: str
    api_key: str | None
    base_url: str | None


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
        self.egress_gate = EgressGate(self.egress_policy, self.redaction_policy)

    def _candidate_chain(self) -> list[_Candidate]:
        """The ordered narrator attempts: configured primary, then each fallback.

        Fallbacks carry no explicit key here — litellm resolves provider keys
        from the environment (e.g. ``OPENROUTER_API_KEY``). Phase 2 will pass
        per-candidate keys from the settings store instead.
        """
        chain = [
            _Candidate(
                provider=self.config.provider,
                model=self.config.model,
                api_key=self.config.api_key or None,
                base_url=self.config.base_url,
            )
        ]
        for entry in self.config.fallback:
            chain.append(
                _Candidate(
                    provider=entry.provider,
                    model=entry.model,
                    api_key=getattr(entry, "api_key", None) or None,
                    base_url=getattr(entry, "base_url", None) or self.config.base_url,
                )
            )
        return chain

    async def generate_insight(self, prompt: str, *, insight_type: str) -> InsightResult:
        """Narrate ``prompt`` via the candidate chain (primary, then fallbacks).

        Each candidate is tried in order, skipping to the next on an
        :class:`~analysis.egress.EgressDenied` (e.g. a cloud fallback without the
        opt-in — a *local* fallback would still pass) or an
        :class:`LLMUnavailableError` (timeout / provider error). If every
        candidate fails, a single :class:`LLMUnavailableError` summarises them.

        Before any byte leaves, the egress policy (ADR-0001 Decision G) is
        enforced fail-closed *per candidate*: the prompt is derived data
        (classified ``PROMPT`` — raw rows are never sent here) and is redacted
        for a cloud destination; the local Ollama path is left untouched.
        """
        chain = self._candidate_chain()
        failures: list[str] = []
        denials: list[EgressDenied] = []
        for candidate in chain:
            # Cloud routes carry the provider prefix in the model already
            # ("deepseek/deepseek-chat"); bare ollama tags get it added for context.
            label = (
                candidate.model
                if "/" in candidate.model
                else f"{candidate.provider}/{candidate.model}"
            )
            try:
                return await self._narrate_once(prompt, candidate, insight_type=insight_type)
            except EgressDenied as exc:
                denials.append(exc)
                failures.append(f"{label}: egress denied ({exc.envelope.reason})")
                log.warning(
                    "narrator: egress denied for %s (%s); trying next candidate",
                    label,
                    exc.envelope.reason,
                )
            except LLMUnavailableError as exc:
                failures.append(f"{label}: {exc}")
                log.warning("narrator: candidate %s failed (%s); trying next", label, exc)

        # Every candidate was refused by the egress gate (e.g. all-cloud with no
        # opt-in) → surface the specific "opt-in required" denial rather than a
        # generic failure, preserving the single-provider contract.
        if denials and len(denials) == len(failures):
            raise denials[0]
        raise LLMUnavailableError(
            f"all {len(chain)} narrator candidate(s) failed: " + " | ".join(failures)
        )

    async def _narrate_once(
        self, prompt: str, candidate: _Candidate, *, insight_type: str
    ) -> InsightResult:
        """One narration attempt against ``candidate`` — egress-gated + redacted."""
        prepared = self.egress_gate.prepare(
            prompt,
            route=EgressRoute(provider=candidate.provider, base_url=candidate.base_url),
            payload_class=PayloadClass.PROMPT,
        )
        payload = prepared.payload
        envelope = prepared.envelope
        if envelope.destination is Destination.CLOUD:
            if prepared.redaction is not None and prepared.redaction.total:
                log.info(
                    "egress redaction: scrubbed %s before cloud send",
                    prepared.redaction.summary(),
                )
            log.info(
                "egress: %s prompt → cloud provider %r (opted in)",
                envelope.payload_class.value,
                candidate.provider,
            )

        import litellm  # deferred import - keeps module-load light

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": payload},
        ]

        model = f"ollama/{candidate.model}" if candidate.provider == "ollama" else candidate.model

        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "timeout": 120,
        }
        if candidate.provider == "ollama":
            kwargs["api_base"] = candidate.base_url
        if candidate.api_key:
            kwargs["api_key"] = candidate.api_key

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
