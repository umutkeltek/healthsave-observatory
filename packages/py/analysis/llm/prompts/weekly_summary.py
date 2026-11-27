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

Findings (computed — narrate these claims, do NOT recompute or invent numbers):
{findings}

Write a 180-300 word narrative. Organize by pillar (Recovery, Sleep,
Activity, Body), skipping any pillar with no lines above, and lead with
the measurement that moved most. End with one or two small, practical
suggestions for the coming week that fit what moved most.
"""


def build_messages(context: dict) -> list[dict]:
    """Build the ``messages`` list for the LLM client."""
    raise NotImplementedError(
        "Weekly-summary prompt assembly deferred to Phase 1.5 - statistical engine must land first"
    )


__all__ = ["SYSTEM_PROMPT", "WEEKLY_SUMMARY_PROMPT_TEMPLATE", "build_messages"]
