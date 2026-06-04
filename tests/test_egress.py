"""Egress trust boundary (`analysis.egress`) — ADR-0001 Decision G.

Pins the default-deny matrix: local always passes; raw observations never leave
regardless of opt-in; derived payloads cross to cloud only with an explicit
opt-in; and every decision yields an auditable envelope.
"""

from __future__ import annotations

import pytest
from analysis.config import LLMConfig
from analysis.egress import (
    Destination,
    EgressDenied,
    EgressGate,
    EgressPolicy,
    PayloadClass,
    classify_destination,
)
from analysis.redaction import RedactionPolicy


def test_ollama_is_local_everything_else_is_cloud() -> None:
    assert classify_destination("ollama") is Destination.LOCAL
    assert classify_destination("OLLAMA") is Destination.LOCAL  # case-insensitive
    assert classify_destination("openai") is Destination.CLOUD
    assert classify_destination("anthropic") is Destination.CLOUD
    assert classify_destination("google") is Destination.CLOUD


def test_local_destination_allows_any_payload_including_raw() -> None:
    # Inside the trust boundary, even raw rows are fine — they never left.
    policy = EgressPolicy(allow_cloud=False)
    for payload in PayloadClass:
        envelope = policy.evaluate(provider="ollama", payload_class=payload)
        assert envelope.allowed
        assert envelope.destination is Destination.LOCAL


def test_cloud_denied_by_default_for_derived_payload() -> None:
    policy = EgressPolicy(allow_cloud=False)
    envelope = policy.evaluate(provider="openai", payload_class=PayloadClass.PROMPT)
    assert not envelope.allowed
    assert "cloud egress not enabled" in envelope.reason


def test_cloud_allowed_for_derived_payload_when_opted_in() -> None:
    policy = EgressPolicy(allow_cloud=True)
    for payload in (
        PayloadClass.FINDINGS,
        PayloadClass.AGGREGATES,
        PayloadClass.EVIDENCE,
        PayloadClass.PROMPT,
    ):
        envelope = policy.evaluate(provider="anthropic", payload_class=payload)
        assert envelope.allowed
        assert envelope.destination is Destination.CLOUD


def test_raw_observations_never_leave_even_when_opted_in() -> None:
    # The privacy promise: opt-in widens derived data, never raw rows.
    policy = EgressPolicy(allow_cloud=True)
    envelope = policy.evaluate(provider="openai", payload_class=PayloadClass.RAW_OBSERVATIONS)
    assert not envelope.allowed
    assert "never leave" in envelope.reason


def test_enforce_raises_on_denial_and_carries_the_envelope() -> None:
    policy = EgressPolicy(allow_cloud=True)
    with pytest.raises(EgressDenied) as exc_info:
        policy.enforce(provider="openai", payload_class=PayloadClass.RAW_OBSERVATIONS)
    assert exc_info.value.envelope.payload_class is PayloadClass.RAW_OBSERVATIONS
    assert not exc_info.value.envelope.allowed


def test_enforce_returns_envelope_on_allow() -> None:
    policy = EgressPolicy(allow_cloud=False)
    envelope = policy.enforce(provider="ollama", payload_class=PayloadClass.PROMPT)
    assert envelope.allowed


def test_from_config_defaults_to_local_only() -> None:
    # Default LLMConfig (ollama, no opt-in) → cloud egress denied.
    policy = EgressPolicy.from_config(LLMConfig())
    assert policy.allow_cloud is False


def test_from_config_honors_explicit_opt_in() -> None:
    policy = EgressPolicy.from_config(LLMConfig(provider="openai", allow_cloud_egress=True))
    assert policy.allow_cloud is True


def test_egress_gate_leaves_local_payload_untouched() -> None:
    gate = EgressGate(EgressPolicy(allow_cloud=False), RedactionPolicy())

    prepared = gate.prepare(
        "owner contact jane.doe@example.com",
        provider="ollama",
        payload_class=PayloadClass.PROMPT,
    )

    assert prepared.payload == "owner contact jane.doe@example.com"
    assert prepared.envelope.destination is Destination.LOCAL
    assert prepared.redaction is None


def test_egress_gate_redacts_cloud_payload_after_allow() -> None:
    gate = EgressGate(EgressPolicy(allow_cloud=True), RedactionPolicy())

    prepared = gate.prepare(
        "owner contact jane.doe@example.com",
        provider="openai",
        payload_class=PayloadClass.PROMPT,
    )

    assert prepared.envelope.destination is Destination.CLOUD
    assert "jane.doe@example.com" not in prepared.payload
    assert "[EMAIL]" in prepared.payload
    assert prepared.redaction is not None
    assert prepared.redaction.total == 1


def test_egress_gate_denies_before_redaction() -> None:
    gate = EgressGate(EgressPolicy(allow_cloud=False), RedactionPolicy())

    with pytest.raises(EgressDenied):
        gate.prepare(
            "owner contact jane.doe@example.com",
            provider="openai",
            payload_class=PayloadClass.PROMPT,
        )
