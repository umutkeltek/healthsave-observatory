# Roadmap

This is the public roadmap for HealthSave Observatory, written as a single
sequence of releases (R0 through R6). It is honest about what is shipped today
versus what is planned, and it deliberately stays high-level — the goal is to show
direction, not to promise dates.

The thread running through every phase is the same: build one owned, canonical,
provenance-tracked record of your body data, make it genuinely useful through
evidence-linked findings, and only then broaden how data gets in and where it can
go.

## The sequence

### R0 — Coherence *(done)*

Settle the product's identity and naming as a private body observatory, and align
the documentation, packaging, and licensing around it. No product features —
purely getting the foundation coherent so everything after it builds in one
direction.

### R1 — Release-grade core *(done)*

Harden the core for real deployment: authentication that is secure by default,
durable rate limiting at the gateway, and a clean separation between storage and
the API surface. The bones of a backend you can actually run.

### R2 — Source / Device / Stream identity *(done)*

The identity foundation: the Source / Device / Stream registry and resolver, a
typed read surface for it, and a durable Stream identifier persisted onto every
canonical observation. This is what lets the Observatory keep readings from
different devices distinct and reconcile them honestly. See
[Source / Device / Stream](concepts/source-device-stream.md). *Verified on real
data sync.*

### R3 — Ship the Observatory web app *(in progress)*

Make the insight-first Observatory web surface the **default** experience:
package it into the standard deployment, make Grafana an optional power-user view
rather than the main interface, and wire the dashboard's narrated cards to a local
language model. The frontend already exists and reads the canonical record — this
phase is packaging and hardening, turning the new identity into the thing you
actually open.

### R4 — The Body Brief loop *(planned)*

The retention core: a first-class **finding-card schema** — each finding stating
its claim, the metric and baseline window behind it, the size of the change, how
complete the underlying data is, which sources it draws from, its confidence,
and, crucially, what it *cannot* conclude — assembled into a **scheduled weekly
Body Brief**. Findings are computed deterministically first; a language model only
narrates them. Report-first, no chat interface. This is the loop meant to bring
you back week after week. See [The Private Body Observatory](concepts/private-body-observatory.md).

### R5 — Agent surface and universal ingest *(planned)*

Two things that turn the Observatory from an app into a platform you build on:

- **An agent surface** — a `healthsave` command-line tool and a local MCP server,
  with scoped read tokens, defaulting to localhost — so your own scripts and AI
  agents can query your body data through a clean, typed interface.
- **Universal ingest** — a generic, secured batch ingest endpoint, plus
  **Android Health Connect** (the first proof that capture is truly
  source-agnostic) and a generic webhook. Both ride on the canonical observation
  model, which is already device-agnostic, so this is a thin surface over plumbing
  that already exists. See [Canonical Observations](concepts/canonical-observations.md).

### R6 — Routing, breadth, and hosted *(planned)*

Generalize where data can go: Home Assistant, MQTT, webhooks, and exports unified
behind **one** egress policy with an outbound queue and an audit trail, so every
route obeys the same trust boundary (see
[Privacy & Egress](concepts/privacy-and-egress.md)). More source adapters are
added as real demand pulls them in, in tiers from first-class support down to
community and generic import/export. A managed hosted option, if it happens, comes
last and starts single-tenant before anything multi-tenant.

## At a glance

| Phase | Focus | State |
|---|---|---|
| R0 | Coherence — identity, docs, licensing | Done |
| R1 | Release-grade core | Done |
| R2 | Source / Device / Stream identity | Done |
| R3 | Ship the Observatory web app as the default surface | In progress |
| R4 | The Body Brief loop (finding cards + weekly brief) | Planned |
| R5 | Agent surface (CLI + local MCP) + universal ingest | Planned |
| R6 | Thin routing + source breadth + hosted | Planned |

---

See also: [The Private Body Observatory](concepts/private-body-observatory.md) ·
[Canonical Observations](concepts/canonical-observations.md) ·
[Privacy & Egress](concepts/privacy-and-egress.md) · [Licensing](licensing.md) ·
[project README](../README.md)
