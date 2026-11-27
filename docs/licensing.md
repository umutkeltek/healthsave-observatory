# Licensing

Different parts of HealthSave Observatory carry different licenses, chosen to fit
what each part is for. This page is the plain-language explanation. The
authoritative, legally binding terms live in [`LICENSING.md`](../LICENSING.md)
and [`TRADEMARK.md`](../TRADEMARK.md) at the repository root — if anything here
is unclear, those files govern.

## The three layers

### Protocol & SDK — Apache License 2.0

The protocol and client surface is licensed under the **Apache License 2.0**.
This is the layer other software can build on:

- the observation **contracts** (the data format),
- the **API client**,
- the **plugin SDK**.

Apache-2.0 is an OSI-approved license, and it carries an explicit patent grant,
which protects both us and anyone adopting it. Other apps, devices, backends,
and your own agents can speak the HealthSave observation format. Clients built
on this layer are welcome, so this layer is the most permissive.

### Core — Elastic License 2.0

The product core — the server you self-host and the Observatory web app — is
licensed under the **Elastic License 2.0 (ELv2)**.

You can read the source, run it, modify it, and host it for yourself. ELv2 does
**not** permit taking the core and offering it to third parties as a managed or
hosted service. That restriction keeps a managed offering available to sustain
development.

Describe this layer as "Licensed under the Elastic License 2.0."

### Premium & managed — commercial (reserved)

Advanced and managed capabilities — things like advanced Body Briefs, report
packs, backup and restore, a managed updater, signed builds, and managed hosting
— are a **commercial** offering, reserved and not part of this source tree. The
self-hosted core stays fully usable on its own; these are additive, paid
conveniences that fund continued development.

## At a glance

| Layer | What's in it | License |
|---|---|---|
| Protocol & SDK | Contracts, API client, plugin SDK | Apache License 2.0 |
| Core | Server you self-host, plus the Observatory web app | Elastic License 2.0 |
| Premium / managed | Advanced briefs, report packs, backup/restore, hosting | Commercial (reserved) |

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

The protocol is a format other software should be able to speak, so it uses
Apache-2.0. The core is something you should be able to run and own yourself, so
it uses the Elastic License 2.0, with a limit that keeps a hosted tier possible.
The premium and managed layer is the commercial piece that pays for the rest.
You can run the core on your own hardware without paying for anything.

---

For the binding terms, see [`LICENSING.md`](../LICENSING.md) and
[`TRADEMARK.md`](../TRADEMARK.md).

See also: [The Private Body Observatory](concepts/private-body-observatory.md) ·
[Roadmap](roadmap.md) · [project README](../README.md)
