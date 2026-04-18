"""Prompt template for the daily morning briefing."""

from .base import SYSTEM_PROMPT

DAILY_BRIEFING_PROMPT_TEMPLATE: str = """\
You are generating today's morning briefing.

Period summary (yesterday):
{period_summary}

Anomalies detected:
{anomalies}

Trends detected:
{trends}

Correlations worth noting:
{correlations}

Data sufficiency: {days_of_data}/{minimum_required} days of history.

Produce a 150-250 word narrative in the style specified by the system
prompt. Lead with the single most actionable finding. Close with one
implementation-intention suggestion ("If X today, then Y") when a
recent behavior pattern supports it.
"""


def build_messages(context: dict) -> list[dict]:
    """Build the ``messages`` list for the LLM client."""
    raise NotImplementedError(
        "Daily-briefing prompt assembly deferred to Phase 1.5 — statistical engine must land first"
    )


__all__ = ["DAILY_BRIEFING_PROMPT_TEMPLATE", "SYSTEM_PROMPT", "build_messages"]
