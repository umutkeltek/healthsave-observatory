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
  * :func:`scrub_narrative` - removes sentences that diagnose, name a
    condition, mention medication or set diet targets, and rounds long
    decimals, before the disclaimer is added.
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
    "General wellness information, not medical advice. If something worries you, talk to a doctor."
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


# The hard limits, enforced on the reply because a small local model does not
# always follow the system prompt. Light wellness context and small everyday
# suggestions are welcome (Umut, 2026-11-16); diagnosis, conditions,
# medication, diet targets and cure claims are not. A sentence that crosses a
# line is removed whole; the rest of the brief stays.
_FORBIDDEN = re.compile(
    r"diagnos|\bdisease|disorder|syndrome|medical condition|underlying condition|"
    r"diabet|hypertens|hypotens|arrhythm|fibrillation|\bafib\b|tachycard|bradycard|"
    r"apnea|apnoea|insomnia|depress|anxiety disorder|infection|\bcovid|\bflu\b|"
    r"cancer|heart attack|stroke|an(a)?emi|thyroid|"
    r"medication|medicine|\bdrug|supplement|melatonin|magnesium|vitamin|ibuprofen|"
    r"aspirin|statin|beta.?blocker|\bdos(e|age)\b|\d\s?(mg|mcg|µg)\b|"
    r"calorie deficit|cut (your |back on )?calories|\bfasting\b|weight.?loss|"
    r"lose weight|\bdiet\b|"
    r"\bcure|\btreat(s|ment|ing)?\b|guarantee|"
    r"medical advice",
    re.IGNORECASE,
)
# A doctor is mentioned only for a reading the engine flagged "severity alert";
# for anything else the one-line note already says it, and a stray "see a
# doctor" about an ordinary change only worries people.
_DOCTOR = re.compile(r"\b(doctor|physician|gp\b|healthcare (provider|professional))", re.IGNORECASE)
# "Significant" reads as a medical or statistical verdict; keep it only next to
# a p-value.
_SIGNIFICANT = re.compile(r"\b(significant)(ly)?\b", re.IGNORECASE)
_HAS_P = re.compile(r"\bp\s*(=|<|-value)", re.IGNORECASE)
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


def _plain_significant(sentence: str) -> str:
    if _HAS_P.search(sentence):
        return sentence

    def swap(match: re.Match[str]) -> str:
        word = "notably" if match.group(2) else "notable"
        return word.capitalize() if match.group(1)[0].isupper() else word

    return _SIGNIFICANT.sub(swap, sentence)


def scrub_narrative(text: str, *, allow_doctor: bool = False) -> ScrubResult:
    """Drop every sentence that crosses a hard limit; round long decimals.

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
            if _FORBIDDEN.search(sentence) or (not allow_doctor and _DOCTOR.search(sentence)):
                if sentence.strip():
                    removed.append(sentence.strip())
            else:
                kept.append(_plain_significant(sentence))
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
