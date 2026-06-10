"""LiteLLM-based LLM client for the Brain-2 narrator.

Phase 1.5 activation: ``generate_insight`` now calls
``litellm.acompletion`` against the configured provider. The ``litellm``
package is imported lazily inside the method body so pytest collection
on Python 3.12/3.14 isn't slowed by the ~80MB LiteLLM import graph on
every touch of this module.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from pydantic import BaseModel

from ..egress import (
    Destination,
    EgressDenied,
    EgressGate,
    EgressPolicy,
    EgressRoute,
    PayloadClass,
    classify_destination,
)
from ..netguard import assert_safe_probe_target
from ..redaction import RedactionPolicy
from .prompts.base import SYSTEM_PROMPT
from .safety import inject_disclaimer

log = logging.getLogger("healthsave.analysis")

# The compose default Ollama endpoint. A cloud LLMConfig inherits this as its
# base_url when LLM_BASE_URL is unset (the field's default), so we must treat it
# as "no custom endpoint" for a non-Ollama provider — otherwise a cloud probe
# would be pointed at the local Ollama and the SSRF guard would false-positive.
_OLLAMA_DEFAULT_BASE_URL = "http://ollama:11434"

# Inline chain-of-thought block emitted by reasoning models (qwen3, DeepSeek R1)
# when the serving layer doesn't separate it out; some chat templates spell it
# ``<thinking>``. ``\Z`` handles an unclosed block — a narrative truncated
# mid-think has no user-facing prose to keep.
_THINK_BLOCK_RE = re.compile(
    r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.IGNORECASE | re.DOTALL
)

# Adaptive budget for reasoning models: when an attempt ends with
# ``finish_reason == "length"`` and NO extractable prose (the model spent the
# whole budget thinking), retry the same candidate once with a boosted
# ``max_tokens`` instead of failing over to a model the user didn't pick.
_TRUNCATION_RETRY_FACTOR = 4
_TRUNCATION_RETRY_CAP = 8192


def _content_to_text(value) -> str:
    """Normalize a message field to plain text.

    OpenAI-compatible servers usually return ``content`` as a string, but the
    spec also allows a list of typed parts (``[{"type": "text", "text": ...}]``)
    and error states can leave it ``None``. Anything non-textual is dropped.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(part, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _extract_narrative(message) -> str:
    """The user-facing prose from a LiteLLM message, reasoning-model aware.

    Reasoning models (OpenAI o-series, qwen3, DeepSeek R1) behind
    OpenAI-compatible endpoints (llama.cpp, vLLM, OpenRouter) may return the
    whole output in ``message.reasoning_content`` with ``content`` empty,
    and/or prefix the prose with an inline ``<think>...</think>`` block.
    Reading only ``content`` makes the briefing degenerate to the bare
    disclaimer (GH issue #13). Prefer ``content``; fall back to
    ``reasoning_content``; strip think blocks from either. Empty result means
    the model produced no narrative at all — the caller treats that as a
    failed attempt so the candidate chain can move on.
    """
    for field in ("content", "reasoning_content"):
        text = _content_to_text(getattr(message, field, None))
        text = _THINK_BLOCK_RE.sub("", text).strip()
        if text:
            return text
    return ""


def _effective_api_base(provider: str, base_url: str | None) -> str | None:
    """The ``api_base`` litellm should use, or None for the built-in endpoint.

    Ollama always gets an endpoint (its configured one, or the compose default).
    A cloud provider gets None — keeping litellm's built-in endpoint — UNLESS a
    genuinely custom ``base_url`` is set; the leftover Ollama default that a
    cloud config inherits is ignored. This is what lets the live DeepSeek path
    (default base_url, no custom endpoint) resolve to None → built-in, while a
    real custom OpenAI-compatible endpoint is honoured and SSRF-validated.
    """
    if provider == "ollama":
        return base_url or _OLLAMA_DEFAULT_BASE_URL
    if base_url and base_url != _OLLAMA_DEFAULT_BASE_URL:
        return base_url
    return None


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
class HealthcheckResult:
    """Outcome of a test-connection probe (ADR-0003 D7).

    Carries no provider response body — only whether the call succeeded, how
    long it took, and a short error string on failure. Persisted as a
    ``provider_healthcheck`` audit event; never any health data.
    """

    ok: bool
    destination: str
    model: str
    latency_ms: int | None = None
    error: str | None = None


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

    async def healthcheck(self, *, timeout: float = 10.0, resolver=None) -> HealthcheckResult:
        """Probe the configured provider with a trivial call — test-connection.

        ADR-0003 D7: validates that the provider + key + endpoint actually work
        BEFORE the user consents to send real findings. The probe sends a fixed
        ``"ping"`` (NO health data), caps output at one token, and uses a short
        timeout. It does NOT pass through the egress *payload* gate — there is no
        derived health data to protect, and a key must be testable pre-consent —
        but it DOES run the SSRF pre-flight on the route, so a cloud ``base_url``
        can't be turned on the server's own network.

        Returns a :class:`HealthcheckResult`; raises
        :class:`~analysis.netguard.SsrfError` (propagated) when the target is
        refused for safety, so the caller can answer ``400`` distinctly from a
        provider failure (``ok=False``).
        """
        provider = self.config.provider
        api_base = _effective_api_base(provider, getattr(self.config, "base_url", None))
        # Classify + SSRF-guard the EFFECTIVE route (api_base is what the call
        # actually hits), so an inherited Ollama default on a cloud config is a
        # no-op and only a genuinely custom endpoint is validated.
        route = EgressRoute(provider=provider, base_url=api_base)
        destination = classify_destination(
            route, trusted_local_hosts=self.egress_policy.trusted_local_hosts
        )
        # SSRF pre-flight (cloud custom base_url only) — may raise SsrfError.
        assert_safe_probe_target(route, destination, resolver=resolver)

        model = f"ollama/{self.config.model}" if provider == "ollama" else self.config.model

        import litellm  # deferred import - single transport (see module docstring)

        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
            "timeout": timeout,
        }
        if api_base is not None:
            kwargs["api_base"] = api_base
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key

        started = time.monotonic()
        try:
            await litellm.acompletion(**kwargs)
        except Exception as exc:  # noqa: BLE001 - report any provider failure as not-ok
            return HealthcheckResult(
                ok=False, destination=destination.value, model=model, error=str(exc)
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        return HealthcheckResult(
            ok=True, destination=destination.value, model=model, latency_ms=latency_ms
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
            "timeout": 120,
        }
        if candidate.provider == "ollama":
            kwargs["api_base"] = candidate.base_url
        if candidate.api_key:
            kwargs["api_key"] = candidate.api_key

        # Adaptive budget: attempt 1 uses the configured max_tokens; if the
        # model is a reasoning model that spent the entire budget thinking
        # (finish_reason "length" + no extractable prose), attempt 2 retries
        # the SAME candidate with a boosted budget before failing over.
        max_tokens = self.config.max_tokens
        tokens_in = tokens_out = 0
        raw = ""
        response = None
        for attempt in (1, 2):
            kwargs["max_tokens"] = max_tokens
            try:
                response = await litellm.acompletion(**kwargs)
            except Exception as exc:  # noqa: BLE001 - intentional wrap-and-raise
                raise LLMUnavailableError(f"LLM call failed: {exc}") from exc

            # Defensive parse: a proxy/server error state can yield no choices
            # or a None message. Surface it as LLMUnavailableError so the
            # candidate chain moves on instead of crashing the run.
            choices = getattr(response, "choices", None) or []
            if not choices:
                raise LLMUnavailableError(f"model {model!r} returned a response with no choices")
            choice = choices[0]
            raw = _extract_narrative(getattr(choice, "message", None))
            finish_reason = getattr(choice, "finish_reason", None)

            # Token accounting accumulates across attempts — a burned thinking
            # budget is still spend the operator should see.
            usage = getattr(response, "usage", None)
            tokens_in += int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
            tokens_out += int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

            if raw:
                if finish_reason == "length":
                    log.warning(
                        "narrator: %s hit the %d-token cap mid-narrative; "
                        "the briefing may be cut short — consider raising LLM_MAX_TOKENS",
                        model,
                        max_tokens,
                    )
                break

            boosted = min(max_tokens * _TRUNCATION_RETRY_FACTOR, _TRUNCATION_RETRY_CAP)
            if finish_reason == "length" and attempt == 1 and boosted > max_tokens:
                log.warning(
                    "narrator: %s spent all %d tokens reasoning with no prose; "
                    "retrying once with max_tokens=%d",
                    model,
                    max_tokens,
                    boosted,
                )
                max_tokens = boosted
                continue
            raise LLMUnavailableError(
                f"model {model!r} returned an empty narrative "
                "(content and reasoning_content both empty after think-block stripping"
                + (", even after a boosted-budget retry" if attempt == 2 else "")
                + ")"
            )

        narrative = inject_disclaimer(raw)
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
