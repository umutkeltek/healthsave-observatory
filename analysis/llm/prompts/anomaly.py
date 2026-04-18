"""Prompt template for anomaly-explanation narratives."""

from .base import SYSTEM_PROMPT

ANOMALY_PROMPT_TEMPLATE: str = """\
A statistical anomaly was detected. Describe it for the user in
80-120 words.

Anomaly:
{anomaly}

Recent context (prior 7 days of this metric):
{recent_context}

Relevant user-profile factors:
{profile_factors}

Do not speculate on causes the data doesn't support. Mention when
the anomaly may be benign (e.g. expected luteal-phase shift, recent
travel, intense workout) if the context supports it. Close with one
concrete suggestion only if the finding actionably suggests one.
"""


def build_messages(anomaly: dict, context: dict) -> list[dict]:
    """Build the ``messages`` list for the LLM client."""
    raise NotImplementedError(
        "Anomaly-prompt assembly deferred to Phase 1.5 — statistical engine must land first"
    )


__all__ = ["ANOMALY_PROMPT_TEMPLATE", "SYSTEM_PROMPT", "build_messages"]
