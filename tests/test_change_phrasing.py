"""Direction words and percent magnitudes stay in agreement."""

from analysis.change_phrasing import normalize_direction_magnitude, percent_change_phrase


def test_percent_change_phrase_negative_positive_and_zero():
    assert percent_change_phrase(-1.7) == "decreased by 1.7%"
    assert percent_change_phrase(1.7) == "increased by 1.7%"
    assert percent_change_phrase(0) == "unchanged (0.0%)"
    assert percent_change_phrase(0.0) == "unchanged (0.0%)"
    # Rounds away to zero at one decimal — not "decreased by 0.0%" or "-0.0%".
    assert percent_change_phrase(-0.04) == "unchanged (0.0%)"
    assert percent_change_phrase(4.84) == "increased by 4.8%"
    assert "-1.7" not in percent_change_phrase(-1.7)
    assert "+1.7" not in percent_change_phrase(1.7)


def test_normalize_strips_sign_next_to_a_direction_word():
    assert normalize_direction_magnitude("HRV decreased by -1.7%.") == "HRV decreased by 1.7%."
    assert normalize_direction_magnitude("HRV decreased by - 1.7%.") == "HRV decreased by 1.7%."
    assert normalize_direction_magnitude("Steps increased by +4.2%.") == "Steps increased by 4.2%."
    assert normalize_direction_magnitude("Weight fell -1.7%.") == "Weight fell 1.7%."
    assert normalize_direction_magnitude("a -1.7% decrease in HRV") == "a 1.7% decrease in HRV"
    assert normalize_direction_magnitude("a +4.2% increase") == "a 4.2% increase"
    assert (
        normalize_direction_magnitude("decreased by −1.7%")  # unicode minus
        == "decreased by 1.7%"
    )
    assert normalize_direction_magnitude("dropped by -1.7 percent") == "dropped by 1.7 percent"
    # Disagreeing sign still yields an absolute magnitude; the direction word stays.
    assert normalize_direction_magnitude("increased by -1.7%") == "increased by 1.7%"
    assert normalize_direction_magnitude("decreased by +2%") == "decreased by 2%"


def test_normalize_leaves_neutral_signed_percents_and_zero_wording():
    unchanged = "Resting HR changed by -1.7% and was otherwise flat."
    assert normalize_direction_magnitude(unchanged) == unchanged
    zero = "HRV was unchanged (0.0%) versus baseline."
    assert normalize_direction_magnitude(zero) == zero
    already = "HRV decreased by 1.7% while steps increased by 4.2%."
    assert normalize_direction_magnitude(already) == already
    # Idempotent, including a sentence that needed a fix.
    fixed = normalize_direction_magnitude("HRV decreased by -1.7% and steps increased by +4.2%.")
    assert fixed == "HRV decreased by 1.7% and steps increased by 4.2%."
    assert normalize_direction_magnitude(fixed) == fixed


def test_normalize_does_not_rewrite_a_bare_signed_percent():
    text = "Week over week the delta was -1.7% to +2.0%, with no direction word."
    assert normalize_direction_magnitude(text) == text
