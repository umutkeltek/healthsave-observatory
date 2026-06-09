"""Egress trust boundary — ADR-0001 Decision G.

A first-class, **default-deny** gate for any data leaving the user's trust
boundary. Decision G rejects a per-plugin ``network: true/false`` bool in favor
of an explicit policy with *destinations* and *payload classes*, plus an
auditable :class:`EgressEnvelope` for every decision. Today the only egress is
the Brain-2 LLM narrator; this module is the layer that decides — before any
byte leaves — *where* a call may go and *what* may ride along.

Two axes:

* **Destination.** Classification is route-based, not provider-name-based
  (ADR-0003 D1): a ``LOCAL`` route (Ollama on a trusted-local host — loopback /
  the bundled sidecar) stays inside the boundary; a ``CLOUD`` route (any named
  cloud provider, OR a *remote* / Ollama-cloud endpoint) crosses it.
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

from .redaction import RedactionPolicy, RedactionResult


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


@dataclass(frozen=True)
class EgressRoute:
    """A resolved LLM endpoint to classify against the trust boundary.

    ``provider`` is the engine/vendor (e.g. ``"ollama"``, ``"deepseek"``);
    ``base_url`` is where it actually points. Classification is route-based, not
    provider-name-based (ADR-0003 D1): a local engine counts as LOCAL only when
    it targets a trusted-local host.
    """

    provider: str
    base_url: str | None = None


# Engines that *can* run on the user's own host. Being one is necessary but not
# sufficient for LOCAL — the route must also point at a trusted-local host.
_LOCAL_ENGINES: frozenset[str] = frozenset({"ollama"})

# Hosts always inside the trust boundary: loopback + the bundled docker sidecar.
_LOCAL_HOSTS: frozenset[str] = frozenset(
    {"localhost", "127.0.0.1", "::1", "[::1]", "ollama", "host.docker.internal"}
)


def _host_of(base_url: str | None) -> str | None:
    """The lowercase hostname of ``base_url``, or ``None`` if absent/unparseable."""
    if not base_url:
        return None
    from urllib.parse import urlparse

    raw = base_url if "://" in base_url else f"//{base_url}"
    host = urlparse(raw).hostname
    return host.lower() if host else None


def classify_destination(
    route: EgressRoute, *, trusted_local_hosts: frozenset[str] = frozenset()
) -> Destination:
    """Classify a route as LOCAL (inside the boundary) or CLOUD (outside).

    A named cloud provider is always CLOUD. A local engine (Ollama) is LOCAL
    only when it targets a trusted-local host — loopback, the bundled sidecar,
    or an explicitly trusted host; a remote or Ollama-cloud endpoint is CLOUD.
    Fail-closed: anything not provably local is treated as cloud (ADR-0003 D1).
    """
    if route.provider.strip().lower() not in _LOCAL_ENGINES:
        return Destination.CLOUD
    host = _host_of(route.base_url)
    if host is None:
        # Zero-config default: no base_url means the bundled loopback sidecar.
        return Destination.LOCAL
    trusted = _LOCAL_HOSTS | {h.strip().lower() for h in trusted_local_hosts}
    return Destination.LOCAL if host in trusted else Destination.CLOUD


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
class PreparedEgressPayload:
    """Payload after the trust-boundary decision and any required redaction."""

    payload: str
    envelope: EgressEnvelope
    redaction: RedactionResult | None = None


@dataclass(frozen=True)
class EgressPolicy:
    """Default-deny egress gate.

    ``allow_cloud`` is the user's explicit opt-in to *any* cloud egress; it
    defaults to ``False`` (self-host, local-only). Even when ``True``,
    ``RAW_OBSERVATIONS`` can never cross the boundary.
    """

    allow_cloud: bool = False
    # Extra hosts the operator declares inside the boundary (e.g. a LAN Ollama).
    # The loopback + bundled-sidecar hosts are always local; this only widens it.
    trusted_local_hosts: frozenset[str] = frozenset()

    @classmethod
    def from_config(cls, llm_config) -> EgressPolicy:
        """Derive the policy from an :class:`~analysis.config.LLMConfig`.

        Reads the explicit ``allow_cloud_egress`` opt-in; a missing attribute
        is treated as opted-out (the safe default), so older configs fail
        closed rather than open.
        """
        return cls(
            allow_cloud=bool(getattr(llm_config, "allow_cloud_egress", False)),
            trusted_local_hosts=frozenset(getattr(llm_config, "trusted_local_hosts", ()) or ()),
        )

    def evaluate(self, *, route: EgressRoute, payload_class: PayloadClass) -> EgressEnvelope:
        """Decide whether this egress is permitted; never raises."""
        destination = classify_destination(route, trusted_local_hosts=self.trusted_local_hosts)

        def envelope(*, allowed: bool, reason: str) -> EgressEnvelope:
            return EgressEnvelope(
                destination=destination,
                payload_class=payload_class,
                provider=route.provider,
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

    def enforce(self, *, route: EgressRoute, payload_class: PayloadClass) -> EgressEnvelope:
        """Evaluate and raise :class:`EgressDenied` unless allowed.

        Returns the (allowed) envelope so the caller can log / persist it.
        """
        envelope = self.evaluate(route=route, payload_class=payload_class)
        if not envelope.allowed:
            raise EgressDenied(envelope)
        return envelope


@dataclass(frozen=True)
class EgressGate:
    """One seam for enforce + redact before payloads leave the host."""

    egress_policy: EgressPolicy
    redaction_policy: RedactionPolicy

    def prepare(
        self,
        payload: str,
        *,
        route: EgressRoute,
        payload_class: PayloadClass,
    ) -> PreparedEgressPayload:
        """Fail closed, then redact cloud-bound derived payloads."""
        envelope = self.egress_policy.enforce(route=route, payload_class=payload_class)
        if envelope.destination is not Destination.CLOUD or not self.redaction_policy.enabled:
            return PreparedEgressPayload(payload=payload, envelope=envelope)

        redaction = self.redaction_policy.apply(payload)
        return PreparedEgressPayload(
            payload=redaction.text,
            envelope=envelope,
            redaction=redaction,
        )
