# Licensing

HealthSave Observatory is **open-core**: different parts of the project carry
different licenses, chosen to fit what each part is for. This page is the friendly
explanation. The authoritative, legally binding terms live in
[`LICENSING.md`](../LICENSING.md) and [`TRADEMARK.md`](../TRADEMARK.md) at the
repository root — if anything here is ever unclear, those files govern.

## The three layers

### Protocol & SDK — Apache-2.0 (open source)

The protocol and client surface is genuinely **open source** under the
**Apache-2.0** license. This is the layer everyone should be free to build on
without hesitation:

- the observation **contracts** (the data format),
- the **API client**,
- the **plugin SDK**.

Apache-2.0 is OSI-approved open source, and it carries an explicit patent grant —
which protects both us and anyone adopting it. We *want* other apps, devices,
backends, and especially your own agents to speak the HealthSave observation
format freely. Every client built on this layer is upside, so this layer is
deliberately the most permissive.

### Core — Elastic License 2.0 (source-available)

The product core — the self-hostable server and the Observatory web app — is
**source-available** under the **Elastic License 2.0 (ELv2)**.

Source-available means you can read the source, run it, modify it, and self-host
it freely for yourself. What ELv2 does **not** permit is taking the core and
offering it to third parties as a managed or hosted service. That single
restriction is what keeps a managed/hosted offering available to sustain the
project's ongoing development.

> **A note on wording:** the core is **source-available**, *not* "open source."
> ELv2 is not an OSI-approved open-source license precisely because of the
> hosted-service restriction. The accurate ways to describe the core are
> *source-available*, *self-hostable*, or *open-core*. The protocol/SDK layer
> above, by contrast, genuinely is open source. We keep this distinction precise
> on purpose.

### Premium & managed — commercial (reserved)

Advanced and managed capabilities — things like advanced Body Briefs, report
packs, backup and restore, a managed updater, signed builds, and managed hosting
— are a **commercial** offering, reserved and not part of this source tree. The
open core stays fully usable on its own; these are additive, paid conveniences
that fund continued development of the open and source-available layers.

## At a glance

| Layer | What's in it | License | Open source? |
|---|---|---|---|
| Protocol & SDK | Contracts, API client, plugin SDK | Apache-2.0 | Yes |
| Core | Self-hostable server + Observatory web app | Elastic License 2.0 | No — source-available |
| Premium / managed | Advanced briefs, report packs, backup/restore, hosting | Commercial (reserved) | No |

## Trademark

The licenses above cover the **code**. The **name** is separate. "HealthSave" and
"HealthSave Observatory" are trademarks, and the code licenses do not grant rights
to use them as your own product identity. In short: you are free to use, modify,
fork, and self-host the software under its respective licenses, but a redistributed
or hosted fork must carry its own distinct name and branding and must not present
itself as HealthSave. The full policy — including exactly what you may do without
asking — is in [`TRADEMARK.md`](../TRADEMARK.md).

## Contributions — DCO

Contributions are accepted under the **Developer Certificate of Origin (DCO)**: a
lightweight sign-off that says you have the right to contribute what you're
contributing. There is **no CLA** required today. A contribution falls under the
license of the part of the tree it touches — Apache-2.0 for the protocol layer,
ELv2 for the core. See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for how to sign off
on a contribution.

## Why split it this way

The split lines up incentives with intent. The protocol is a standard, so it's
fully open to spread as widely as possible. The core is something you should be
able to run and own completely, so it's source-available and self-hostable — with
just enough restriction to keep a sustainable hosted tier possible. The premium
and managed layer is the commercial piece that pays for the rest. You can run the
whole open core, forever, on your own hardware, without paying for anything.

---

For the binding terms, see [`LICENSING.md`](../LICENSING.md) and
[`TRADEMARK.md`](../TRADEMARK.md).

See also: [The Private Body Observatory](concepts/private-body-observatory.md) ·
[Roadmap](roadmap.md) · [project README](../README.md)
