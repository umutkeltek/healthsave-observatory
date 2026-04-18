"""LiteLLM-based LLM client for the Brain-2 narrator.

Phase 1 ships this shell only. The ``litellm`` dependency is declared
in ``pyproject.toml`` / ``requirements.txt`` but is NOT imported here
yet — wiring lands in Phase 1.5 alongside the real engine calls.
"""


class HealthLLMClient:
    """Thin wrapper around LiteLLM with provider config + disclaimer enforcement.

    The client:
      * Reads provider + model + base URL + API key from :class:`analysis.config.LLMConfig`.
      * Falls back through :attr:`LLMConfig.fallback` on failure.
      * Tracks token usage into ``analysis_runs`` via
        :meth:`track_usage`.
      * Passes every generated narrative through
        :func:`analysis.llm.safety.inject_disclaimer` before returning.
    """

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

    async def generate_insight(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a narrative from the given prompts.

        Hooks in Phase 1.5 will:
          1. Call ``litellm.acompletion`` with the configured provider.
          2. On failure, iterate through ``config.fallback`` providers.
          3. Pass the raw response through
             :func:`analysis.llm.safety.inject_disclaimer`.
          4. Log tokens + cost via :meth:`track_usage`.
        """
        raise NotImplementedError("LLM integration deferred to Phase 1.5 — litellm wiring pending")

    async def track_usage(self, run_id: int, response) -> None:
        """Persist token counts and estimated cost to ``analysis_runs``."""
        raise NotImplementedError(
            "LLM usage tracking deferred to Phase 1.5 — litellm wiring pending"
        )
