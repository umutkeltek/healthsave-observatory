"""Content redaction (`analysis.redaction`) — the *what* half of the egress gate.

Pins the detector behavior, idempotence, the masked/hashed methods, and — the
load-bearing test — that a realistic briefing prompt full of metric numbers,
z-scores, p-values and ISO timestamps survives a redaction pass byte-for-byte.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from analysis.redaction import (
    RedactionCategory,
    RedactionPolicy,
    redact_text,
)


def test_email_phone_and_id_are_masked() -> None:
    text = "reach me at jane.doe@example.com or 555-123-4567, SSN 123-45-6789"
    result = RedactionPolicy().apply(text)

    assert "jane.doe@example.com" not in result.text
    assert "555-123-4567" not in result.text
    assert "123-45-6789" not in result.text
    assert "[EMAIL]" in result.text
    assert "[PHONE]" in result.text
    assert "[ID]" in result.text
    assert result.counts[RedactionCategory.EMAIL] == 1
    assert result.counts[RedactionCategory.PHONE] == 1
    assert result.counts[RedactionCategory.ID] == 1


def test_url_and_ipv4_are_masked() -> None:
    result = RedactionPolicy().apply("posted to https://example.com/p from 10.0.12.34 today")
    assert "[URL]" in result.text
    assert "[IPV4]" in result.text
    assert "https://example.com/p" not in result.text
    assert "10.0.12.34" not in result.text


def test_possessive_name_is_masked_but_device_noun_survives() -> None:
    result = RedactionPolicy().apply("source: Maria's Apple Watch")
    assert result.text == "source: [NAME]'s Apple Watch"
    assert result.counts[RedactionCategory.NAME] == 1


def test_long_opaque_numeric_id_is_masked() -> None:
    result = RedactionPolicy().apply("device id 1234567890 enrolled")
    assert "1234567890" not in result.text
    assert "[ID]" in result.text


def test_redaction_is_idempotent() -> None:
    text = "email a@b.com phone 555-123-4567 owner Sam's ring"
    once = RedactionPolicy().apply(text)
    twice = RedactionPolicy().apply(once.text)
    assert twice.text == once.text
    assert twice.total == 0  # nothing left to redact on the second pass


def test_disabled_policy_passes_text_through_unchanged() -> None:
    text = "email a@b.com leaks if disabled"
    result = RedactionPolicy(enabled=False).apply(text)
    assert result.text == text
    assert result.total == 0


def test_hash_method_is_deterministic_stable_and_salt_sensitive() -> None:
    text = "primary a@b.com, again a@b.com, other c@d.com"
    hashed = RedactionPolicy(method="hash", salt="s1").apply(text)

    tokens = [tok for tok in hashed.text.replace(",", " ").split() if tok.startswith("[EMAIL:")]
    assert len(tokens) == 3
    assert tokens[0] == tokens[1]  # same value → same token
    assert tokens[0] != tokens[2]  # different value → different token

    # Same input + same salt is reproducible; a different salt changes the token.
    assert RedactionPolicy(method="hash", salt="s1").apply(text).text == hashed.text
    assert RedactionPolicy(method="hash", salt="s2").apply(text).text != hashed.text


def test_summary_reports_counts_without_values() -> None:
    result = RedactionPolicy().apply("a@b.com and e@f.com, id 1234567890")
    assert result.counts[RedactionCategory.EMAIL] == 2
    summary = result.summary()
    assert "email=2" in summary
    assert "id=1" in summary
    assert "@" not in summary  # never leaks the value itself


def test_category_subset_only_redacts_selected() -> None:
    policy = RedactionPolicy(categories=frozenset({RedactionCategory.EMAIL}))
    result = policy.apply("a@b.com 555-123-4567")
    assert "[EMAIL]" in result.text
    assert "555-123-4567" in result.text  # PHONE not in the selected set


def test_from_llm_config_defaults_on_and_honors_opt_out() -> None:
    # Missing attribute → fail safe (on).
    assert RedactionPolicy.from_llm_config(SimpleNamespace()).enabled is True

    opted_out = RedactionPolicy.from_llm_config(SimpleNamespace(redact_cloud_prompts=False))
    assert opted_out.enabled is False

    salted = RedactionPolicy.from_llm_config(SimpleNamespace(redaction_salt="pepper"))
    assert salted.salt == "pepper"


def test_realistic_briefing_prompt_is_not_corrupted() -> None:
    """The guardrail: pure metric content must pass through byte-for-byte.

    Numbers that *look* risky — multi-digit sample counts, signed deltas,
    p-values with many decimals, ISO timestamps — must never be mistaken for
    phone numbers or opaque IDs.
    """
    metrics = {
        "heart_rate": {
            "mean": 62.4,
            "min": 48,
            "max": 121,
            "stddev": 8.37,
            "sample_count": 1440,
            "delta_pct_vs_baseline": -3.2,
            "p_value": 0.0123456789,
            "z": 2.34,
            "last_seen": "2026-06-03T07:00:00+00:00",
        },
        "hrv": {"mean": 54.1, "min": 22, "max": 98, "sample_count": 288, "z": -1.07},
    }
    prompt = (
        f"{json.dumps(metrics, indent=2)}\n"
        "- heart_rate: high deviation, severity=warning, z=2.34\n"
        "- hrv: down trend (slope=-0.45, p=0.003)\n"
        "- heart_rate ~ hrv: r=-0.61 (spearman)\n"
    )

    result = RedactionPolicy().apply(prompt)
    assert result.text == prompt
    assert result.total == 0


def test_redact_text_convenience_uses_default_policy() -> None:
    assert redact_text("ping a@b.com") == "ping [EMAIL]"
