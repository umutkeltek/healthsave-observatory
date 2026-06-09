# Privacy & Egress

The promise of a private body observatory is only as good as its trust boundary.
HealthSave Observatory's boundary is simple to state and built to be auditable:
**your raw observations never leave your host unless you explicitly send them
somewhere, and the system defaults to sending nothing.**

This page explains exactly what can and cannot cross that line, and how you stay
in control of it.

## The trust boundary

Everything that matters runs on your hardware. Capture, the canonical record, the
statistical findings engine, the Observatory dashboard, and a local language
model all live inside your host or your own network. The raw, reading-level data
— your actual heart rates, sleep sessions, and everything else — is meant to stay
there.

Crossing out of that boundary is treated as the exceptional case, not the
default. There is no path where intimate biometrics quietly flow to a third party
because you didn't find a setting to turn off.

## Default-deny egress

The Observatory's egress policy is **default-deny**. Out of the box, nothing is
sent anywhere outside your host. A destination only receives data if you have
explicitly enabled it, and only the class of data that destination is permitted
to receive.

Destinations are categorized by how much they can be trusted with, and the
permitted payload narrows as trust drops:

- **On your host / your own network** (a local dashboard, Home Assistant, a local
  broker on your LAN) can be allowed richer data — but still only with your
  explicit acknowledgement.
- **Your own remote server or webhook** receives derived results by default; raw
  readings require clear, deliberate consent and are recorded.
- **A third-party cloud service** (including any cloud language model) can receive
  **only derived findings or aggregates, opt-in, and after on-device redaction —
  never raw observations.**

The policy fails closed: if a destination's trust level is unknown, or a payload
hasn't been classified, the default action is to **deny**. You have to opt
something in; you never have to discover that it was opted in for you.

## What's allowed to cross — and what isn't

The Observatory distinguishes a few classes of data, and the boundary treats them
very differently:

| Data class | What it is | Can it leave your host? |
|---|---|---|
| **Raw observations** | Your actual reading-level data | No — never to a cloud service; stays on your host / your own network |
| **Derived findings** | The statistical conclusions computed from your data | Only with explicit opt-in, and redacted before any cloud egress |
| **Aggregates** | Summaries and roll-ups, not individual readings | Only with explicit opt-in, and redacted before any cloud egress |

The line is deliberate: even when you choose to use a cloud model, what it sees is
the *conclusion* and a scrubbed summary — not the underlying stream of your body's
data.

## Cloud LLM egress is opt-in, and redacted on-device

HealthSave Observatory can optionally use a cloud language model to help narrate
your findings. That capability is **off by default** and is the most tightly
constrained path in the system:

1. **You opt in.** Nothing goes to a cloud model unless you turn it on.
2. **Only derived data is eligible.** Raw observations are categorically excluded
   from cloud egress. Only findings and aggregates can be candidates.
3. **It is redacted on-device first.** Before anything leaves, an on-device
   redaction step scrubs the payload, so only the necessary, sanitized derived
   content crosses the boundary.

The deterministic statistical engine still computes the findings locally. A cloud
model, if you enable one, is only putting already-computed, already-scrubbed
findings into words.

## Local Ollama never leaves the network

If you would rather keep everything local — and the Observatory is designed so
that you can — you can run a **local language model with Ollama**. In that
configuration the narration runs on your own hardware and **the data never leaves
your network at all.** The full loop, including the worded findings, stays inside
your boundary, and cloud egress simply never happens. Local is the default posture
the product is built around; cloud is the opt-in exception.

## An auditable posture

The point of all this is not just to be private but to be *checkably* private.
The egress boundary is a single, explicit policy rather than a scatter of
per-feature switches: every destination has a declared trust level, every payload
has a declared class, and routes are recorded so you can see what left, when, and
to where. Privacy here is an inspectable property of the system, not a marketing
claim — which is the whole point of owning the observatory in the first place.

---

See also: [The Private Body Observatory](private-body-observatory.md) ·
[Canonical Observations](canonical-observations.md) ·
[Source / Device / Stream](source-device-stream.md) · [Roadmap](../roadmap.md) ·
[project README](../../README.md)
