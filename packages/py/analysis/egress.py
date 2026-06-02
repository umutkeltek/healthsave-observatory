"""Egress trust boundary — ADR-0001 Decision G.

A first-class, **default-deny** gate for any data leaving the user's trust
boundary. Decision G rejects a per-plugin ``network: true/false`` bool in favor
of an explicit policy with *destinations* and *payload classes*, plus an
auditable :class:`EgressEnvelope` for every decision. Today the only egress is
the Brain-2 LLM narrator; this module is the layer that decides — before any
byte leaves — *where* a call may go and *what* may ride along.

Two axes:

* **Destination.** A ``LOCAL`` model (Ollama on the user's own host) stays
  inside the trust boundary; a ``CLOUD`` model (OpenAI / Anthropic / Google /
  any non-Ollama provider) crosses it.
* **Payload class.** ``RAW_OBSERVATIONS`` must **never** leave — that is the
  product's privacy promise, enforced unconditionally. Derived
  findings / aggregates / evidence and an assembled narration prompt MAY leave,
  but only to a destination the user explicitly opted into.

Self-host default (zero config): **local Ollama only — no cloud egress.**
Pointing at a cloud provider is necessary but not sufficient; the user must
*also* opt in (``allow_cloud_egress``), so a stray ``base_url`` can't silently
exfiltrate derived health data. The policy is pure (no I/O); callers log /
persist the returned envelope for the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Destination(StrEnum):
    """Where an egress is headed, relative to the user's trust boundary."""

    LOCAL = "local"  # user's own host (Ollama) — inside the boundary
    CLOUD = "cloud"  # third-party provider — outside the boundary


class PayloadClass(StrEnum):
    """What kind of data an egress carries, in increasing sensitivity."""

    RAW_OBSERVATIONS = "raw_observations"  # individual rows — never leaves
    FINDINGS = "findings"  # derived structured findings (anomalies, scores)
    AGGREGATES = "aggregates"  # rollups / period summaries
    EVIDENCE = "evidence"  # citation snippets / RAG context
    PROMPT = "prompt"  # an assembled narration prompt (derived data)


# Derived (non-raw) payload classes eligible to cross to an opted-in cloud
# destination. RAW_OBSERVATIONS is deliberately absent — it can never leave.
_CLOUD_ELIGIBLE: frozenset[PayloadClass] = frozenset(
    {
        PayloadClass.FINDINGS,
        PayloadClass.AGGREGATES,
        PayloadClass.EVIDENCE,
        PayloadClass.PROMPT,
    }
)

# Provider strings that denote a LOCAL model. Everything else is CLOUD.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama"})


def classify_destination(provider: str) -> Destination:
    """Map an LLM provider string to a :class:`Destination`."""
    return Destination.LOCAL if provider.strip().lower() in _LOCAL_PROVIDERS else Destination.CLOUD


@dataclass(frozen=True)
class EgressEnvelope:
    """Auditable record of one egress decision (Decision G's audit half)."""

    destination: Destination
    payload_class: PayloadClass
    provider: str
    allowed: bool
    reason: str


class EgressDenied(RuntimeError):
    """Raised when an egress is denied by policy. Fail-closed by design."""

    def __init__(self, envelope: EgressEnvelope) -> None:
        super().__init__(f"egress denied: {envelope.reason}")
        self.envelope = envelope


@dataclass(frozen=True)
class EgressPolicy:
    """Default-deny egress gate.

    ``allow_cloud`` is the user's explicit opt-in to *any* cloud egress; it
    defaults to ``False`` (self-host, local-only). Even when ``True``,
    ``RAW_OBSERVATIONS`` can never cross the boundary.
    """

    allow_cloud: bool = False

    @classmethod
    def from_config(cls, llm_config) -> EgressPolicy:
        """Derive the policy from an :class:`~analysis.config.LLMConfig`.

        Reads the explicit ``allow_cloud_egress`` opt-in; a missing attribute
        is treated as opted-out (the safe default), so older configs fail
        closed rather than open.
        """
        return cls(allow_cloud=bool(getattr(llm_config, "allow_cloud_egress", False)))

    def evaluate(self, *, provider: str, payload_class: PayloadClass) -> EgressEnvelope:
        """Decide whether this egress is permitted; never raises."""
        destination = classify_destination(provider)

        def envelope(*, allowed: bool, reason: str) -> EgressEnvelope:
            return EgressEnvelope(
                destination=destination,
                payload_class=payload_class,
                provider=provider,
                allowed=allowed,
                reason=reason,
            )

        if destination is Destination.LOCAL:
            return envelope(allowed=True, reason="local destination inside trust boundary")

        # Cloud from here. Raw rows can never leave, opt-in or not.
        if payload_class not in _CLOUD_ELIGIBLE:
            return envelope(
                allowed=False,
                reason=f"{payload_class.value} may never leave the trust boundary",
            )
        if not self.allow_cloud:
            return envelope(
                allowed=False,
                reason="cloud egress not enabled (self-host default is local-only)",
            )
        return envelope(allowed=True, reason="derived payload to opted-in cloud destination")

    def enforce(self, *, provider: str, payload_class: PayloadClass) -> EgressEnvelope:
        """Evaluate and raise :class:`EgressDenied` unless allowed.

        Returns the (allowed) envelope so the caller can log / persist it.
        """
        envelope = self.evaluate(provider=provider, payload_class=payload_class)
        if not envelope.allowed:
            raise EgressDenied(envelope)
        return envelope
