# Licensing — HealthSave Observatory

> **One-line summary:** the **protocol is open** (Apache-2.0) so anyone — and any agent — can speak
> the HealthSave observation format; the **product core is source-available** (Elastic License 2.0)
> so you can self-host it freely, while offering it to third parties as a managed service is not
> permitted; the **premium/managed features are commercial** and reserved. The split maximizes
> adoption of the open *standard* while keeping the project sustainable.

This file is the authoritative map of which license governs which path. Where a directory carries
its own `LICENSE` file, that file governs that directory and everything under it. Everything not
covered by a directory-level `LICENSE` is governed by the root [`LICENSE`](./LICENSE)
(Elastic License 2.0).

---

## The three layers

| Layer | Paths | License | Why this license |
|---|---|---|---|
| **Protocol & client surface** (the open standard) | `contracts/` · `packages/py/contracts/` · `packages/ts/api-client/` · `packages/py/plugin_sdk/` · *(future)* `cli/`, SDKs | **Apache-2.0** | We *want* other apps, devices, backends, and especially your own agents to speak the HealthSave observation format without fear. Apache (not MIT) because of its explicit **patent grant** — defensive for us and for adopters. This layer spreading is pure upside: every client built on it points back at HealthSave. |
| **Product core** (the self-hostable server) | repo root + everything else: `apps/api`, `apps/worker`, `apps/agents`, `packages/py/storage`, `packages/py/analysis`, `apps/web`, `db/`, `deploy/`, `integrations/`, … | **Elastic License 2.0** (source-available) | ELv2 lets anyone read, run, modify, and self-host the core — but **does not permit offering it to third parties as a hosted or managed service**. That keeps a managed/hosted tier available to sustain the project. |
| **Premium / managed** (the paid value) | *not in this repo* — advanced Body Briefs, report packs, backup/restore, managed updater, signed builds, managed single-tenant hosting | **Proprietary / commercial** | The premium/managed features live outside the source tree — a commercial product that funds ongoing development. The open core stays fully usable without them. |

## How to describe it publicly (precise wording matters)

- The **protocol/SDK/CLI** layer **is open source** (Apache-2.0, OSI-approved). Say so freely.
- The **core server** is **source-available / self-hostable under the Elastic License 2.0**.
  **Do NOT call the core "open source"** — ELv2 is not OSI-approved (it restricts hosted-as-a-service).
  Correct phrasings: *"source-available,"* *"self-hostable,"* *"open-core."*
- The **premium/managed** layer is a **commercial product**.

## Why the split

Three goals, balanced:

1. **Interoperability (Apache protocol).** The more clients, devices, and agents speak the
   observation format, the more useful the standard becomes — so the protocol/SDK layer is fully
   open and permissively licensed.
2. **Sustainable self-hosting (ELv2 core).** Anyone can self-host the core for free; what ELv2
   withholds is *reselling it as a managed service*, which keeps a hosted/managed tier available to
   fund continued development.
3. **A name people can trust (trademark).** The code licenses don't grant use of the marks — see
   [`TRADEMARK.md`](./TRADEMARK.md). Forks are welcome but use their own name, so "HealthSave"
   reliably means this project.

We deliberately don't permissively license the whole thing (that would allow a hosted clone with no
way to fund the project) and don't restrict the protocol (that would discourage the
developer/agent ecosystem we want). The split keeps the standard open and the project viable.

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
- **Copyright holder.** The notices read **`Umut Keltek`** (the individual rights-holder),
  pending registration of a brand/entity — switch to the entity name once it exists, across
  [`NOTICE`](./NOTICE) and the directory `LICENSE` appendix lines.

## Inventory of license files

- Root [`LICENSE`](./LICENSE) — Elastic License 2.0 (core).
- `contracts/LICENSE`, `packages/py/contracts/LICENSE`, `packages/ts/api-client/LICENSE`,
  `packages/py/plugin_sdk/LICENSE` — Apache-2.0 (protocol & client surface).
- [`NOTICE`](./NOTICE) — attribution.
- [`TRADEMARK.md`](./TRADEMARK.md) — brand policy.
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — DCO contributor terms.

> This document is informational, not legal advice. Get counsel before finalizing the public
> relicense announcement and before adopting any dual-license/CLA.
