"""Content redaction — the *what* half of the egress trust boundary.

:mod:`analysis.egress` (ADR-0001 Decision G) decides *whether* a payload may
leave the user's host. This module decides *what content* rides along when it
does: before an assembled narration prompt crosses to a ``CLOUD`` destination,
identifiers are scrubbed out of it. The local Ollama path is never redacted —
that data never left the trust boundary, so there is nothing to strip and full
fidelity helps the local model.

Design constraints, deliberately:

* **Pure & dependency-free.** Standard-library ``re``/``hashlib`` only — no ML
  model, no network, no third-party package. The redactor is deterministic and
  auditable, which is the same property the statistical engine is held to.
* **Idempotent.** Re-running :meth:`RedactionPolicy.apply` on already-redacted
  text changes nothing — replacement tokens never re-match a detector.
* **Conservative on numbers.** Health prompts are mostly metric values, z-scores,
  p-values, sample counts and ISO timestamps. Detectors are tuned so none of
  those are mistaken for identifiers; the regression test in
  ``tests/test_redaction.py`` pins a realistic briefing prompt as byte-identical
  except for injected PII.

Two redaction methods:

* ``mask`` (default) — replace each match with a class token, e.g. ``[EMAIL]``.
  Fully non-reversible; the cloud model sees only that *an* email was present.
* ``hash`` — replace with a salted, truncated digest token, e.g.
  ``[EMAIL:1a2b3c4d]``. Still non-reversible, but the *same* identifier maps to
  the *same* token, so the model can reason that two mentions are the same
  device/person without ever seeing the real value.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum


class RedactionCategory(StrEnum):
    """A class of identifier the redactor recognizes, in detector priority order."""

    EMAIL = "email"
    URL = "url"
    IPV4 = "ipv4"
    PHONE = "phone"
    ID = "id"  # SSN / MRN / card-like / long opaque numeric identifiers
    NAME = "name"  # possessive owner names (e.g. "Maria's Apple Watch")


# Detectors run in this order; each match is replaced before the next category is
# scanned, so a later, broader pattern never re-matches an earlier token. EMAIL
# is first (its local part can look like a name); NAME is last (broadest).
#
# Number safety is the load-bearing detail:
#   * ID requires >=9 contiguous digits AND no adjacent digit/dot, so decimals
#     (``0.123456789``), z-scores, p-values and short integers never match.
#   * PHONE requires explicit separators or a leading ``+``, so a bare integer
#     (sample counts, slopes) is never read as a phone number.
#   * NAME matches only a possessive proper noun (``Word's``); over-redacting an
#     occasional weekday ("Monday's") is harmless and never corrupts metric JSON.
_DETECTORS: tuple[tuple[RedactionCategory, re.Pattern[str]], ...] = (
    (RedactionCategory.EMAIL, re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    (RedactionCategory.URL, re.compile(r"https?://[^\s\"'<>)\]]+")),
    (RedactionCategory.IPV4, re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    (
        RedactionCategory.PHONE,
        re.compile(r"(?<![\w.])(?:\+\d[\d .()\-]{7,}\d|\b\d{3}[.\-]\d{3}[.\-]\d{4}\b)(?![\w.])"),
    ),
    (
        RedactionCategory.ID,
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b|(?<![\d.\-])\d{9,}(?![\d.])"),
    ),
    (RedactionCategory.NAME, re.compile(r"\b[A-Z][a-z]+(?=(?:'|’)s\b)")),
)

_ALL_CATEGORIES: frozenset[RedactionCategory] = frozenset(RedactionCategory)


def _digest(value: str, salt: str) -> str:
    """Stable, non-reversible short token for ``value`` under ``salt``."""
    return hashlib.blake2s(f"{salt}:{value}".encode(), digest_size=4).hexdigest()


@dataclass(frozen=True)
class RedactionResult:
    """Outcome of one redaction pass: the cleaned text plus per-category counts.

    ``counts`` carries only *how many* of each category were replaced — never the
    values — so it is safe to log for the audit trail.
    """

    text: str
    counts: dict[RedactionCategory, int]

    @property
    def total(self) -> int:
        """Total identifiers replaced across all categories."""
        return sum(self.counts.values())

    def summary(self) -> str:
        """Compact, value-free description for audit logs, e.g. ``"email=1 id=2"``."""
        return " ".join(f"{cat.value}={n}" for cat, n in self.counts.items() if n) or "none"


@dataclass(frozen=True)
class RedactionPolicy:
    """How derived content is scrubbed before it crosses to a cloud destination.

    ``enabled`` defaults to ``True`` so the opt-in cloud tier is safe by
    construction; turning it off is an explicit choice. ``method`` selects masked
    vs. salted-hash tokens; ``salt`` only affects ``hash`` output.
    """

    enabled: bool = True
    method: str = "mask"  # "mask" | "hash"
    salt: str = ""
    categories: frozenset[RedactionCategory] = _ALL_CATEGORIES

    @classmethod
    def from_llm_config(cls, llm_config) -> RedactionPolicy:
        """Derive the policy from an :class:`~analysis.config.LLMConfig`.

        Missing attributes fail safe (redaction *on*), so an older config without
        the field still scrubs cloud prompts rather than leaking them.
        """
        return cls(
            enabled=bool(getattr(llm_config, "redact_cloud_prompts", True)),
            salt=str(getattr(llm_config, "redaction_salt", "") or ""),
        )

    def _token(self, category: RedactionCategory, value: str) -> str:
        """Replacement token for one matched ``value`` of ``category``."""
        label = category.value.upper()
        if self.method == "hash":
            return f"[{label}:{_digest(value, self.salt)}]"
        return f"[{label}]"

    def apply(self, text: str) -> RedactionResult:
        """Scrub identifiers from ``text``; return the cleaned text + counts.

        A disabled policy returns ``text`` unchanged with zero counts. The pass is
        single-shot per category in detector order and therefore idempotent.
        """
        counts: dict[RedactionCategory, int] = {cat: 0 for cat in RedactionCategory}
        if not self.enabled or not text:
            return RedactionResult(text=text, counts=counts)

        result = text
        for category, pattern in _DETECTORS:
            if category not in self.categories:
                continue

            def _replace(match: re.Match[str], _category: RedactionCategory = category) -> str:
                counts[_category] += 1
                return self._token(_category, match.group(0))

            result = pattern.sub(_replace, result)

        return RedactionResult(text=result, counts=counts)


def redact_text(text: str, *, policy: RedactionPolicy | None = None) -> str:
    """Convenience: scrub ``text`` with ``policy`` (default policy if omitted)."""
    return (policy or RedactionPolicy()).apply(text).text
