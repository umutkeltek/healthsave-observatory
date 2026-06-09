"""Egress trust boundary (`analysis.egress`) — ADR-0001 Decision G + ADR-0003 D1.

Pins the default-deny matrix: a *local route* always passes; raw observations
never leave regardless of opt-in; derived payloads cross to cloud only with an
explicit opt-in; and every decision yields an auditable envelope. Classification
is route-based (provider + where it points), not provider-name-based.
"""

from __future__ import annotations

import pytest
from analysis.config import LLMConfig
from analysis.egress import (
    Destination,
    EgressDenied,
    EgressGate,
    EgressPolicy,
    EgressRoute,
    PayloadClass,
    classify_destination,
)
from analysis.redaction import RedactionPolicy


def test_classify_destination_is_route_based() -> None:
    # A local engine with no base_url → the bundled loopback sidecar (LOCAL).
    assert classify_destination(EgressRoute("ollama")) is Destination.LOCAL
    assert classify_destination(EgressRoute("OLLAMA")) is Destination.LOCAL  # case-insensitive
    # Loopback / bundled-sidecar hosts are inside the boundary.
    for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://ollama:11434"):
        assert classify_destination(EgressRoute("ollama", url)) is Destination.LOCAL
    # A *remote* Ollama (or Ollama-cloud) is NOT local — the key hardening.
    assert (
        classify_destination(EgressRoute("ollama", "http://192.168.1.50:11434"))
        is Destination.CLOUD
    )
    assert classify_destination(EgressRoute("ollama", "https://ollama.com")) is Destination.CLOUD
    # Named cloud providers are always cloud, whatever the base_url.
    assert classify_destination(EgressRoute("openai")) is Destination.CLOUD
    assert (
        classify_destination(EgressRoute("deepseek", "http://localhost:1234")) is Destination.CLOUD
    )


def test_classify_destination_honors_trusted_local_hosts() -> None:
    remote = EgressRoute("ollama", "http://nas.local:11434")
    assert classify_destination(remote) is Destination.CLOUD  # untrusted by default
    assert (
        classify_destination(remote, trusted_local_hosts=frozenset({"nas.local"}))
        is Destination.LOCAL
    )


def test_local_destination_allows_any_payload_including_raw() -> None:
    # Inside the trust boundary, even raw rows are fine — they never left.
    policy = EgressPolicy(allow_cloud=False)
    for payload in PayloadClass:
        envelope = policy.evaluate(route=EgressRoute("ollama"), payload_class=payload)
        assert envelope.allowed
        assert envelope.destination is Destination.LOCAL


def test_cloud_denied_by_default_for_derived_payload() -> None:
    policy = EgressPolicy(allow_cloud=False)
    envelope = policy.evaluate(route=EgressRoute("openai"), payload_class=PayloadClass.PROMPT)
    assert not envelope.allowed
    assert "cloud egress not enabled" in envelope.reason


def test_remote_ollama_is_treated_as_cloud() -> None:
    # A remote Ollama with no opt-in is denied just like any other cloud route.
    policy = EgressPolicy(allow_cloud=False)
    envelope = policy.evaluate(
        route=EgressRoute("ollama", "http://10.0.0.9:11434"),
        payload_class=PayloadClass.PROMPT,
    )
    assert not envelope.allowed
    assert envelope.destination is Destination.CLOUD


def test_cloud_allowed_for_derived_payload_when_opted_in() -> None:
    policy = EgressPolicy(allow_cloud=True)
    for payload in (
        PayloadClass.FINDINGS,
        PayloadClass.AGGREGATES,
        PayloadClass.EVIDENCE,
        PayloadClass.PROMPT,
    ):
        envelope = policy.evaluate(route=EgressRoute("anthropic"), payload_class=payload)
        assert envelope.allowed
        assert envelope.destination is Destination.CLOUD


def test_raw_observations_never_leave_even_when_opted_in() -> None:
    # The privacy promise: opt-in widens derived data, never raw rows.
    policy = EgressPolicy(allow_cloud=True)
    envelope = policy.evaluate(
        route=EgressRoute("openai"), payload_class=PayloadClass.RAW_OBSERVATIONS
    )
    assert not envelope.allowed
    assert "never leave" in envelope.reason


def test_enforce_raises_on_denial_and_carries_the_envelope() -> None:
    policy = EgressPolicy(allow_cloud=True)
    with pytest.raises(EgressDenied) as exc_info:
        policy.enforce(route=EgressRoute("openai"), payload_class=PayloadClass.RAW_OBSERVATIONS)
    assert exc_info.value.envelope.payload_class is PayloadClass.RAW_OBSERVATIONS
    assert not exc_info.value.envelope.allowed


def test_enforce_returns_envelope_on_allow() -> None:
    policy = EgressPolicy(allow_cloud=False)
    envelope = policy.enforce(route=EgressRoute("ollama"), payload_class=PayloadClass.PROMPT)
    assert envelope.allowed


def test_from_config_defaults_to_local_only() -> None:
    # Default LLMConfig (ollama, no opt-in) → cloud egress denied.
    policy = EgressPolicy.from_config(LLMConfig())
    assert policy.allow_cloud is False


def test_from_config_honors_explicit_opt_in() -> None:
    policy = EgressPolicy.from_config(LLMConfig(provider="openai", allow_cloud_egress=True))
    assert policy.allow_cloud is True


def test_from_config_carries_trusted_local_hosts() -> None:
    policy = EgressPolicy.from_config(LLMConfig(trusted_local_hosts=["nas.local"]))
    assert "nas.local" in policy.trusted_local_hosts


def test_egress_gate_leaves_local_payload_untouched() -> None:
    gate = EgressGate(EgressPolicy(allow_cloud=False), RedactionPolicy())

    prepared = gate.prepare(
        "owner contact jane.doe@example.com",
        route=EgressRoute("ollama"),
        payload_class=PayloadClass.PROMPT,
    )

    assert prepared.payload == "owner contact jane.doe@example.com"
    assert prepared.envelope.destination is Destination.LOCAL
    assert prepared.redaction is None


def test_egress_gate_redacts_cloud_payload_after_allow() -> None:
    gate = EgressGate(EgressPolicy(allow_cloud=True), RedactionPolicy())

    prepared = gate.prepare(
        "owner contact jane.doe@example.com",
        route=EgressRoute("openai"),
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
            route=EgressRoute("openai"),
            payload_class=PayloadClass.PROMPT,
        )
