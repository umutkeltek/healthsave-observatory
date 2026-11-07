"""Percent-change wording that keeps a direction word and its number in agreement.

A signed percent next to a direction word ("decreased by -1.7%") is a double
negative. Direction words take an absolute magnitude ("decreased by 1.7%").
A signed number is only for neutral verbs ("changed by -1.7%").

Brain-1 claims and Brain-2 prompt inputs both use :func:`percent_change_phrase`.
:func:`normalize_direction_magnitude` is a light guard on narrator prose, for
when a small local model still copies a minus sign onto a direction word.
"""

from __future__ import annotations

import re

# Longest-first is unnecessary with the trailing word boundary, but it keeps
# "decreased" from ever being considered a prefix of a shorter alternative.
_DIRECTION_WORDS: tuple[str, ...] = (
    "decreased",
    "decreases",
    "decreasing",
    "decrease",
    "dropped",
    "drops",
    "dropping",
    "drop",
    "fell",
    "falls",
    "falling",
    "fall",
    "declined",
    "declines",
    "declining",
    "decline",
    "reduced",
    "reduces",
    "reducing",
    "reduction",
    "lowered",
    "lowers",
    "lowering",
    "lower",
    "increased",
    "increases",
    "increasing",
    "increase",
    "rose",
    "rises",
    "rising",
    "rise",
    "grew",
    "grows",
    "growing",
    "growth",
    "gained",
    "gains",
    "gaining",
    "gain",
    "improved",
    "improves",
    "improving",
    "improvement",
    "higher",
    "lost",
    "loss",
    "down",
    "up",
)

_WORD = "|".join(_DIRECTION_WORDS)
_SIGN = r"[-+\u2212\u2013]"
_NUM = r"\d+(?:\.\d+)?"
_UNIT = r"(?:%|\s+percent(?:age)?\b)"

# "decreased by -1.7%", "increase of +2%", "fell -1.7 percent"
_WORD_THEN_SIGNED = re.compile(
    rf"\b(?P<word>{_WORD})\b"
    rf"(?P<mid>\s+(?:by|of))?"
    rf"\s*(?P<sign>{_SIGN})\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT})",
    re.IGNORECASE,
)

# "a -1.7% decrease", "+4.2% increase"
_SIGNED_THEN_WORD = re.compile(
    rf"(?P<sign>{_SIGN})\s*(?P<num>{_NUM})\s*"
    rf"(?P<unit>{_UNIT})\s+(?P<word>{_WORD})\b",
    re.IGNORECASE,
)


def percent_change_phrase(delta_pct: float, *, digits: int = 1) -> str:
    """Phrase a percent delta so the direction word and the number agree.

    Positive → ``"increased by 1.7%"``. Negative → ``"decreased by 1.7%"``.
    A value that rounds to zero at ``digits`` → ``"unchanged (0.0%)"``.
    """
    magnitude = abs(float(delta_pct))
    rendered = f"{magnitude:.{digits}f}"
    if rendered == f"{0:.{digits}f}":
        return f"unchanged ({rendered}%)"
    if delta_pct > 0:
        return f"increased by {rendered}%"
    return f"decreased by {rendered}%"


def _drop_sign_after_word(match: re.Match[str]) -> str:
    word = match.group("word")
    mid = match.group("mid") or ""
    glue = f"{mid} " if mid else " "
    return f"{word}{glue}{match.group('num')}{match.group('unit')}"


def _drop_sign_before_word(match: re.Match[str]) -> str:
    return f"{match.group('num')}{match.group('unit')} {match.group('word')}"


def normalize_direction_magnitude(text: str) -> str:
    """Strip a sign that sits on the same percent as a direction word.

    ``"decreased by -1.7%"`` becomes ``"decreased by 1.7%"``. Neutral verbs
    are left alone (``"changed by -1.7%"``). Idempotent.
    """
    if not text:
        return text
    cleaned = _WORD_THEN_SIGNED.sub(_drop_sign_after_word, text)
    return _SIGNED_THEN_WORD.sub(_drop_sign_before_word, cleaned)


__all__ = ["normalize_direction_magnitude", "percent_change_phrase"]
