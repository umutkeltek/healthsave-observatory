"""The narrator's reply is held to the hard limits after the fact.

Light wellness context and small everyday suggestions are welcome in a brief
(decided 2026-11-16). Diagnosis, named conditions, medication and doses, diet
or weight-loss targets and cure claims are not, so a sentence carrying one is
removed whole.
"""

from __future__ import annotations

from analysis.llm.safety import (
    DISCLAIMER_TEXT,
    has_substance,
    inject_disclaimer,
    scrub_narrative,
)

WELCOME = [
    "Your heart rate variability rose 15.5% over the past 30 days.",
    "Regular movement is linked to better heart health.",
    "A short walk after lunch would close most of today's step gap.",
    "A steady bedtime often helps sleep.",
]
FORBIDDEN = [
    "This pattern can be a sign of hypertension.",
    "A raised resting heart rate can come with an infection.",
    "Taking magnesium before bed may help.",
    "Try 200 mg of caffeine less per day.",
    "A small calorie deficit would bring your weight down.",
    "We cannot diagnose this.",
    "This is not medical advice.",
]


def test_wellness_context_and_small_suggestions_stay():
    text = " ".join(WELCOME)
    result = scrub_narrative(text)
    assert result.text == text
    assert result.removed == []


def test_diagnosis_conditions_medication_and_diet_targets_are_removed():
    result = scrub_narrative("\n\n".join([WELCOME[0], *FORBIDDEN, WELCOME[2]]))
    assert len(result.removed) == len(FORBIDDEN)
    assert WELCOME[0] in result.text and WELCOME[2] in result.text
    for word in ("hypertension", "infection", "magnesium", "mg", "calorie", "diagnose"):
        assert word not in result.text


def test_long_decimals_are_rounded():
    result = scrub_narrative(
        "Slope 0.32088987764182425 per day, p-value 0.007068236510369564, average 53.142857."
    )
    assert result.text == "Slope 0.321 per day, p-value 0.007, average 53.1."


def test_headings_and_list_items_keep_their_place():
    text = "**Sleep**\n- Average 7.2 hours from 7 nights.\n\n**Activity**\n- Steps fell 9.4%."
    assert scrub_narrative(text).text == text


def test_one_short_disclaimer_replaces_a_model_written_one():
    result = scrub_narrative("Steps fell 9.4% this week.\n\nThis is not medical advice.")
    final = inject_disclaimer(result.text)
    assert final.count("not medical advice") == 1
    assert final.endswith(DISCLAIMER_TEXT)
    assert len(DISCLAIMER_TEXT) < 100


def test_a_reply_with_only_headings_left_has_no_substance():
    result = scrub_narrative("**Recovery**\nThis looks like apnea.\n**Sleep**\nTake melatonin.")
    assert not has_substance(result.text)
    assert has_substance("**Sleep**\nAverage sleep was 7.2 hours.")


def test_doctor_is_mentioned_only_for_an_alert():
    text = "Resting heart rate is down 4.8%. Mention it to your doctor if it continues."
    assert scrub_narrative(text).text == "Resting heart rate is down 4.8%."
    assert scrub_narrative(text, allow_doctor=True).text == text


def test_significant_needs_a_p_value():
    assert scrub_narrative("A significant drop of 4.8%.").text == "A notable drop of 4.8%."
    assert scrub_narrative("Significantly lower than usual.").text == "Notably lower than usual."
    kept = "The trend is statistically significant (p = 0.007)."
    assert scrub_narrative(kept).text == kept
