"""Prompt template for the daily morning briefing."""

from .base import SYSTEM_PROMPT

DAILY_BRIEFING_PROMPT_TEMPLATE: str = """\
You are generating today's morning briefing.

Period summary (yesterday; averages, with your recent usual level):
{period_summary}

Detected anomalies (values more than a few standard deviations from the
user's 30-day personal baseline):
{anomalies}

If the anomaly block reads as "no unusual readings vs baseline", say so in
one sentence and move on - do not invent anomalies. If it lists any,
describe each in one or two sentences, highest severity first.

Trends detected:
{trends}

Correlations worth noting:
{correlations}

Days with data in this period: {days_of_data}.

Write a 120-200 word narrative in the style the system prompt sets. Lead
with the largest change, with its own number from above. End with one small,
practical suggestion for today that fits that change.
"""


def build_messages(context: dict) -> list[dict]:
    """Build the ``messages`` list for the LLM client."""
    raise NotImplementedError(
        "Daily-briefing prompt assembly deferred - engine formats the template directly for now"
    )


__all__ = ["DAILY_BRIEFING_PROMPT_TEMPLATE", "SYSTEM_PROMPT", "build_messages"]
