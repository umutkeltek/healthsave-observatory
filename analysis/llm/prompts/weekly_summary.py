"""Prompt template for the weekly summary."""

from .base import SYSTEM_PROMPT

WEEKLY_SUMMARY_PROMPT_TEMPLATE: str = """\
You are generating the weekly health summary.

Period summary (past 7 days):
{period_summary}

Week-over-week comparison:
{week_comparison}

Trends this week:
{trends}

Correlations observed:
{correlations}

Data sufficiency: {days_of_data}/{minimum_required} days of history.

Produce a 200-350 word narrative. Organize by pillar (Recovery, Sleep,
Activity, Body) and emphasize the single dimension that moved most.
Close with one proposed focus area for the coming week.
"""


def build_messages(context: dict) -> list[dict]:
    """Build the ``messages`` list for the LLM client."""
    raise NotImplementedError(
        "Weekly-summary prompt assembly deferred to Phase 1.5 — statistical engine must land first"
    )


__all__ = ["SYSTEM_PROMPT", "WEEKLY_SUMMARY_PROMPT_TEMPLATE", "build_messages"]
