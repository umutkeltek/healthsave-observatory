"""The narrator's reply is held to the system prompt's rules after the fact.

Sentences below are ones llama3.1:8b actually wrote for a synthetic year
before the filter existed (2026-11-16): every one of ten briefs carried at
least one interpretation or piece of advice.
"""

from __future__ import annotations

from analysis.llm.safety import (
    DISCLAIMER_TEXT,
    has_substance,
    inject_disclaimer,
    scrub_narrative,
)

SEEN = [
    "We've detected an upward trend in HRV over the past 30 days. "
    "This may indicate improved cardiovascular resilience.",
    "Your heart rate was elevated. This could be a sign of increased physical or mental activity.",
    "Steps and active energy moved together, suggesting you are using energy efficiently.",
    "If you notice a rise today, consider taking a short walk to help regulate heart rate.",
    "It's essential to consult a healthcare provider to rule out any underlying conditions.",
    "Your weight remained stable, which is a positive development for your overall health.",
]


def test_interpretations_and_advice_are_removed_and_facts_stay():
    result = scrub_narrative("\n\n".join(SEEN))
    assert "upward trend in HRV over the past 30 days" in result.text
    assert "Your heart rate was elevated." in result.text
    for phrase in (
        "cardiovascular",
        "sign of",
        "efficiently",
        "consider",
        "healthcare provider",
        "overall health",
    ):
        assert phrase not in result.text
    assert len(result.removed) == 6


def test_long_decimals_are_rounded():
    result = scrub_narrative(
        "Slope 0.32088987764182425 per day, p-value 0.007068236510369564, average 53.142857."
    )
    assert result.text == "Slope 0.321 per day, p-value 0.007, average 53.1."


def test_headings_and_list_items_keep_their_place():
    text = "**Sleep**\n- Average 7.2 hours from 7 nights.\n\n**Activity**\n- Steps fell 9.4%."
    assert scrub_narrative(text).text == text


def test_a_model_written_disclaimer_is_replaced_by_the_reviewed_one():
    result = scrub_narrative("Steps fell 9.4% this week.\n\nThis is not medical advice.")
    final = inject_disclaimer(result.text)
    assert final.count("not medical advice") == 1
    assert final.endswith(DISCLAIMER_TEXT)


def test_a_reply_with_only_headings_left_has_no_substance():
    result = scrub_narrative("**Recovery**\nYour fitness improved.\n**Sleep**\nThis is healthy.")
    assert not has_substance(result.text)
    assert has_substance("**Sleep**\nAverage sleep was 7.2 hours.")
