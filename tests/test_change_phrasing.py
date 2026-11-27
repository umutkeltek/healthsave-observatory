from analysis.change_phrasing import percent_change_phrase


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
