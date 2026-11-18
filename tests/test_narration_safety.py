"""The narrator's reply is held to the hard limits after the fact.

Light wellness context and small everyday suggestions are welcome in a brief
(decided 2026-11-16). Diagnosis, named conditions, medication and doses, diet
or weight-loss targets and cure claims are not, so a sentence carrying one is
removed whole.
"""

from __future__ import annotations

import pytest
from analysis.llm.safety import (
    DISCLAIMER_TEXT,
    drop_doubled_minus,
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


# A fall word already says "minus". The cases come from the two earlier
# attempts (7c34dfb, PR #48) plus the wording seen in briefs ("down -4.8%").
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Resting heart rate was down -4.8%.", "Resting heart rate was down 4.8%."),
        (
            "Your activity decreased by -1.7% compared with your recent baseline.",
            "Your activity decreased by 1.7% compared with your recent baseline.",
        ),
        ("Activity DECREASED by \u22121.7%.", "Activity DECREASED by 1.7%."),
        ("Steps fell \u20134.8%.", "Steps fell 4.8%."),
        ("Resting heart rate fell by -2%.", "Resting heart rate fell by 2%."),
        ("Weight fell -1.7%.", "Weight fell 1.7%."),
        ("Activity dropped by -0.4%.", "Activity dropped by 0.4%."),
        ("Activity declined by -.5%.", "Activity declined by .5%."),
        ("Activity was reduced by -1.0%.", "Activity was reduced by 1.0%."),
        ("Activity was down by -1.7 %.", "Activity was down by 1.7 %."),
        ("HRV decreased by - 1.7%.", "HRV decreased by 1.7%."),
        ("Steps dropped by -1.7 percent.", "Steps dropped by 1.7 percent."),
        (
            "The share decreased by -1.7 percentage points.",
            "The share decreased by 1.7 percentage points.",
        ),
        ("A drop of -4.8% in steps.", "A drop of 4.8% in steps."),
        ("Sleep was lower by -3%.", "Sleep was lower by 3%."),
        ("A -1.7% decrease in HRV.", "A 1.7% decrease in HRV."),
        ("HRV ran -4.8% below your usual.", "HRV ran 4.8% below your usual."),
        (
            "Resting heart rate was down **-4.8%** this week.",
            "Resting heart rate was down **4.8%** this week.",
        ),
        ("HRV was **-4.8%** lower.", "HRV was **4.8%** lower."),
        (
            "Resting heart rate was down -4.8% to 53.1 bpm.",
            "Resting heart rate was down 4.8% to 53.1 bpm.",
        ),
        (
            "HRV fell -4.8% and steps dropped by -2.1%.",
            "HRV fell 4.8% and steps dropped by 2.1%.",
        ),
    ],
)
def test_a_fall_word_drops_the_minus_of_its_percent(text, expected):
    assert drop_doubled_minus(text) == expected
    assert drop_doubled_minus(expected) == expected  # idempotent
    assert scrub_narrative(text).text == expected  # and the brief path applies it


@pytest.mark.parametrize(
    "text",
    [
        # No fall word: a signed figure is the figure.
        "pct_change=-1.7%",
        "Resting heart rate: change -4.8%.",
        "Activity: -1.7% vs your recent baseline.",
        "Activity: \u22121.7% vs your recent baseline.",
        "Resting HR changed by -1.7% and was otherwise flat.",
        "The correlation was -0.3.",
        "Week over week the delta was -1.7% to +2.0%, with no direction word.",
        # Already right.
        "Activity decreased by 1.7%.",
        "HRV decreased by 1.7% while steps increased by 4.2%.",
        "HRV was unchanged (0.0%) versus baseline.",
        # Word and sign disagree: dropping the sign would flip the computed
        # direction, so the contradiction stays visible.
        "Activity increased by -1.7%.",
        "Steps rose -4.8%.",
        "Steps were up -4.8%.",
        "Activity decreased by +2%.",
        # A doubled plus is clumsy, not wrong: out of scope.
        "Steps increased by +4.2%.",
        "A +4.2% increase.",
        # Ranges and bounds: the sign belongs to an endpoint.
        "Activity decreased by -1.7% to -0.5%.",
        "Activity decreased by -1.7%\u2013-0.5%.",
        "Activity decreased by -1.7\u2013-0.5%.",
        "Activity decreased by -1.7% or more.",
        "Activity decreased by -1.7% or less.",
        "Activity decreased by -1.7%\nto -0.5%.",
        "Activity decreased by -1.7%\u00a0to -0.5%.",
        "Activity decreased by -1.7%\nor more.",
        "Activity decreased by -1.7%\u00a0or less.",
        "The rate decreased from -1.7% to -2.1%.",
        "Daily change was between -2% and -4.8% lower.",
        # Not a percent: temperatures and other signed measurements.
        "Temperature decreased to -1.7 \u00b0C.",
        "Temperature decreased by -1.7 \u00b0C.",
        "Wrist temperature fell -0.3 \u00b0C below your usual.",
        # Parenthesised raw figure, a label, an adjective, and a line break.
        "Resting heart rate fell (-4.8%) this week.",
        "Down: -4.8% versus last week.",
        "A lower -2.0% change than last week.",
        "Steps were down\n-4.8% on Monday.",
        "- 4.8% lower than last week.",
        "The countdown -4.8% mark.",
    ],
)
def test_legitimate_signed_text_is_left_alone(text):
    assert drop_doubled_minus(text) == text
