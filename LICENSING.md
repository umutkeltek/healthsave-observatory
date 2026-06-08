# Licensing — HealthSave Observatory

> **One-line summary:** the **protocol is open (Apache-2.0)** so anyone can build on it and
> agents can speak it; the **product core is source-available (Elastic License 2.0)** so no
> better-funded competitor can take it and sell it as a hosted service; the **premium layer is
> proprietary** so the crown jewels stay ours. This split is deliberate — it maximizes adoption
> of the *standard* while protecting the *business*.

This file is the authoritative map of which license governs which path. Where a directory carries
its own `LICENSE` file, that file governs that directory and everything under it. Everything not
covered by a directory-level `LICENSE` is governed by the root [`LICENSE`](./LICENSE)
(Elastic License 2.0).

---

## The three layers

| Layer | Paths | License | Why this license |
|---|---|---|---|
| **Protocol & client surface** (the open standard) | `contracts/` · `packages/py/contracts/` · `packages/ts/api-client/` · `packages/py/plugin_sdk/` · *(future)* `cli/`, SDKs | **Apache-2.0** | We *want* other apps, devices, backends, and especially your own agents to speak the HealthSave observation format without fear. Apache (not MIT) because of its explicit **patent grant** — defensive for us and for adopters. This layer spreading is pure upside: every client built on it points back at HealthSave. |
| **Product core** (the self-hostable server) | repo root + everything else: `apps/api`, `apps/worker`, `apps/agents`, `packages/py/storage`, `packages/py/analysis`, `apps/web`, `db/`, `deploy/`, `integrations/`, … | **Elastic License 2.0** (source-available) | ELv2 lets anyone read, run, modify, and self-host the core — but **forbids providing it to third parties as a hosted or managed service**. That single clause is the moat against a competitor with more marketing cloning our hosted tier. |
| **Premium / managed** (the paid value) | *not in this repo* — advanced Body Briefs, report packs, backup/restore, managed updater, signed builds, managed single-tenant hosting | **Proprietary / commercial** | The highest-value differentiators are withheld from the source tree entirely, so even a permitted self-hoster or forker does not get them. This is where revenue compounds. |

## How to describe it publicly (precise wording matters)

- The **protocol/SDK/CLI** layer **is open source** (Apache-2.0, OSI-approved). Say so freely.
- The **core server** is **source-available / self-hostable under the Elastic License 2.0**.
  **Do NOT call the core "open source"** — ELv2 is not OSI-approved (it restricts hosted-as-a-service).
  Correct phrasings: *"source-available,"* *"self-hostable,"* *"open-core."*
- The **premium/managed** layer is a **commercial product**.

## Why this is the smart move (the defensive design)

Four compounding levers make life hard for a bigger, better-funded competitor — without
crippling adoption:

1. **ELv2 on the core** — they cannot legally stand up our server as a managed SaaS for others.
   The most likely "outspend us on marketing and host it" attack is closed by the license itself.
2. **Trademark on the name** (see [`TRADEMARK.md`](./TRADEMARK.md)) — even a permitted fork
   **cannot call itself "HealthSave" or "HealthSave Observatory."** A forker must rebrand, which
   forfeits our SEO, App Store presence, reviews, and word-of-mouth. For a solo builder, brand +
   distribution is often a stronger moat than the code license.
3. **Proprietary premium layer** — the features people actually pay for never enter the source
   tree, so forking the core yields an incomplete product.
4. **Apache protocol** — counter-intuitively *protective*: the more clients, devices, and agents
   speak our observation format, the more HealthSave becomes the default standard, and standards
   are sticky. Adoption of the open layer deepens the moat around the closed layer.

What we deliberately **do not** do: we don't MIT/Apache the whole thing (that invites a hosted
clone and kills the wealth path), and we don't ELv2/proprietary the protocol (that scares off the
agent/developer ecosystem we want). The split gets both.

## Contributor terms

Contributions are accepted under the **Developer Certificate of Origin (DCO)** — see
[`CONTRIBUTING.md`](./CONTRIBUTING.md). A contribution falls under the license of the path it
touches (Apache-2.0 for the protocol leaves, ELv2 for the core). A **CLA** is **not** required
today; one may be introduced **only if** we later adopt an AGPL-3.0 + commercial dual-license for
the core (a CLA is what would let us sell commercial exceptions). Until then, DCO keeps the bar low.

## Deferred decisions (revisit, don't pre-commit)

- **Core license: ELv2 vs AGPL-3.0 + commercial.** Staying ELv2 for now (protective, simple).
  Revisit if/when a genuine contributor community forms and OSI-"open source" legitimacy becomes
  worth more than the absolute anti-SaaS protection. Switching ELv2 → AGPL is possible later;
  going the other way is not — so ELv2-now keeps options open. A CLA would need to land *before*
  that switch.
- **Standalone packaging.** The Apache leaves are licensed in place today. To publish any of them
  as an independent `pip`/`npm` package later, give that directory its own build manifest
  (`pyproject.toml`); `packages/ts/api-client` already has its own `package.json`. This is a
  packaging step, not a directory move.
- **Copyright holder.** The notices currently read `HealthSave`. Set this to your legal name or
  entity (e.g. once an entity exists) across [`NOTICE`](./NOTICE) and the directory `LICENSE`
  appendix lines.

## Inventory of license files

- Root [`LICENSE`](./LICENSE) — Elastic License 2.0 (core).
- `contracts/LICENSE`, `packages/py/contracts/LICENSE`, `packages/ts/api-client/LICENSE`,
  `packages/py/plugin_sdk/LICENSE` — Apache-2.0 (protocol & client surface).
- [`NOTICE`](./NOTICE) — attribution.
- [`TRADEMARK.md`](./TRADEMARK.md) — brand policy.
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — DCO contributor terms.

> This document is informational, not legal advice. Get counsel before finalizing the public
> relicense announcement and before adopting any dual-license/CLA.
