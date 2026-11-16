"""Medical safety layer.

See ``docs/HEALTH_DOMAIN_SUPPLEMENT.md`` §5.1. This module is the last
line of defense between the LLM and the user:

  * :data:`CRITICAL_THRESHOLDS` - hard numbers that OVERRIDE the LLM
    entirely. When crossed we emit a static alert, never a generated
    narrative.
  * :data:`DISCLAIMER_TEXT` - mandatory disclaimer appended to every
    non-critical insight.
  * :func:`inject_disclaimer` - idempotent helper that appends the
    disclaimer only when the LLM has not already produced one.
  * :func:`scrub_narrative` - removes sentences that interpret health or
    give advice, and rounds long decimals, before the disclaimer is added.
"""

import re
from dataclasses import dataclass

CRITICAL_THRESHOLDS: dict[str, float] = {
    # These OVERRIDE normal analysis. Direct alert, no LLM narration.
    "spo2_below": 90,  # Sustained SpO2 < 90% → seek medical attention
    "systolic_above": 180,  # Hypertensive crisis
    "diastolic_above": 120,  # Hypertensive crisis
    "glucose_below": 54,  # Severe hypoglycemia → emergency
    "glucose_above": 250,  # DKA risk → emergency
    "resting_hr_above": 120,  # At rest, sustained → seek attention
    "resting_hr_below": 35,  # Bradycardia → seek attention
    "temp_deviation_above": 2.0,  # >2 C above baseline → possible high fever
}


DISCLAIMER_TEXT: str = (
    "This is not medical advice. HealthSave analyses are informational only "
    "and cannot diagnose conditions or replace professional evaluation. "
    "If you are experiencing symptoms or have concerns about a reading, "
    "please consult a qualified healthcare provider."
)


CRITICAL_ALERT_TEMPLATE: str = (
    "IMPORTANT: {metric_name} ({value} {unit}) is outside the expected safe range.\n\n"
    "This is not a diagnosis. This reading may indicate a condition that "
    "warrants prompt medical evaluation. Please consult a healthcare provider.\n\n"
    "If you are experiencing symptoms (chest pain, difficulty breathing, "
    "confusion, or feel unwell), seek immediate medical attention."
)


def inject_disclaimer(text: str) -> str:
    """Append :data:`DISCLAIMER_TEXT` to ``text`` unless already present.

    The check is case-insensitive and looks for the canonical phrase
    ``"not medical advice"`` anywhere in the narrative, so an LLM that
    already produced its own disclaimer is not double-stamped.
    """
    if "not medical advice" in text.lower():
        return text
    separator = "" if text.endswith(("\n", "\r")) else "\n\n"
    return f"{text}{separator}{DISCLAIMER_TEXT}"


# What the narrator must not say, enforced on the reply because a small local
# model does not always follow the system prompt. Measured on llama3.1:8b
# before this filter: every brief of ten carried at least one such sentence
# ("may indicate improved cardiovascular resilience", "consider taking a short
# walk"). A sentence that matches is removed whole; the rest of the brief stays.
_INTERPRETATION = re.compile(
    r"cardiovascular|heart health|overall health|well-?being|fitness|"
    r"healthier|\bhealthy\b|improv|deteriorat|worsen|"
    r"\b(positive|negative|encouraging|concerning|worrying|good|bad)\s+"
    r"(trend|development|sign|change|indicator|news)|"
    r"\bsign of\b|\bstress|illness|\bsick|disease|infection|inflammat|overtrain|"
    r"immun|fatigue|underlying|medical condition|diagnos|"
    r"efficien|resilien|ability to (adapt|recover)",
    re.IGNORECASE,
)
_ADVICE = re.compile(
    r"\b(consider|try to|try incorporating|aim (for|to)|you (should|could|may want|might want)|"
    r"make sure|focus on|set(ting)? a goal|engage in|incorporat|increase your|reduce your|"
    r"it'?s (essential|important|worth) to|consult|see a doctor|healthcare provider|"
    r"medical advice|seek)\b",
    re.IGNORECASE,
)
_LONG_DECIMAL = re.compile(r"\d+\.\d{3,}")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ScrubResult:
    """A narrative with rule-breaking sentences removed, and what was removed."""

    text: str
    removed: list[str]


def _round_long_decimal(match: re.Match[str]) -> str:
    value = float(match.group(0))
    return f"{value:.3f}" if abs(value) < 1 else f"{value:.1f}"


def scrub_narrative(text: str) -> ScrubResult:
    """Drop every sentence that interprets health or gives advice; round long decimals.

    Runs line by line so headings and list items keep their place. A line whose
    every sentence is removed disappears. A model-written medical disclaimer is
    removed too: :func:`inject_disclaimer` then appends the reviewed one.
    """
    removed: list[str] = []
    kept_lines: list[str] = []
    for line in text.splitlines():
        sentences = _SENTENCE_END.split(line)
        kept = []
        for sentence in sentences:
            if _INTERPRETATION.search(sentence) or _ADVICE.search(sentence):
                if sentence.strip():
                    removed.append(sentence.strip())
            else:
                kept.append(sentence)
        new_line = " ".join(kept).rstrip()
        if not new_line.strip() and line.strip():
            continue
        kept_lines.append(new_line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    cleaned = _LONG_DECIMAL.sub(_round_long_decimal, cleaned)
    return ScrubResult(text=cleaned, removed=removed)


def _is_heading(line: str) -> bool:
    line = line.strip()
    return line.startswith("#") or (line.startswith("**") and line.endswith(("**", "**:")))


def has_substance(text: str) -> bool:
    """True when a scrubbed narrative still holds at least one sentence beyond headings."""
    return any(
        len(line.strip("*#_ ").split()) >= 3
        for line in text.splitlines()
        if line.strip() and not _is_heading(line)
    )
