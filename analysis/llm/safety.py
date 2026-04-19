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
"""

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
