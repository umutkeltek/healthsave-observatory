# Roadmap: Android & webhooks

> **Status: Planned (roadmap item R5).** Everything on this page describes
> *universal ingest* that is not yet shipped. For sources you can capture today,
> see the [capture index](./index.md) — Apple Health, the Whoop and Amazfit
> plugins, and the Garmin / Samsung importers are all live.

Apple Health, the direct plugins, and the file importers already prove that
Apple is the on-ramp, not the boundary. The next step is to make *adding a new
source* a first-class, self-service operation rather than a per-source plugin or
importer. That is what the planned universal ingest layer is for.

## Generic ingest API

The planned `POST /api/v2/ingest/batch` endpoint accepts canonical observations
from **any** registered source. It is the generalization of the per-source
ingest paths into one envelope contract:

- **HMAC-signed.** Each request is signed with a per-source secret so the server
  can verify the sender without sharing credentials in the clear.
- **Idempotent envelope.** Each batch carries an idempotency key, so retries and
  re-sends never inflate your data — the same guarantee the shipped ingest paths
  already provide.
- **Canonical observations.** The body is a batch of normalized observations
  rather than a vendor-specific export, so a source author normalizes once and
  the server does not need source-specific parsing.

The existing `/api/apple/batch` ingest stays a **frozen v1 contract** for the
iOS app; the generic envelope evolves under `/api/v2/`.

## The envelope concept

At a high level, every batch posted to the generic ingest API declares its
identity using the same model every shipped source already resolves to —
[Source / Device / Stream](../concepts/source-device-stream.md) — and then
carries the readings as canonical observations:

- **Source** — which integration is posting (your Android app, a registered
  webhook, a custom script).
- **Device** — the physical emitter the readings came from.
- **Stream** — the source + device + metric join the observations belong to.
- **Observations** — the normalized readings themselves (metric, timestamp,
  value, units), already in canonical shape.

Because the envelope speaks the same canonical model as Apple Health, Whoop, and
the importers, data posted this way lands in the same per-metric tables and flows
to the same dashboards, findings, and routes — no special-casing downstream.

## Android Health Connect

Native Android capture into the generic ingest API is planned: an Android client
reads from Health Connect and posts canonical observations to
`/api/v2/ingest/batch`, mirroring how the iOS app pushes Apple Health today. This
closes the gap for users without an Apple device while keeping a single
canonical record.

## Generic webhook / native API sources

The same envelope makes any registered source a first-class capture path:

- A vendor that can post a webhook signs and sends canonical observations on its
  own schedule.
- A custom script or notebook can push readings without needing a bespoke plugin.
- A direct connector (for example, the planned Oura connector modelled on
  Whoop's) can target the generic envelope instead of forking the ingest path.

If you cannot wait for the generic API, the routes that exist today still cover a
lot: implement the `Source` plugin contract and poll your device yourself (how
the [Whoop and Amazfit plugins](./plugins-whoop-amazfit.md) work), or use a CLI
[importer](./importers-garmin-samsung.md) for file exports.

## See also

- [Capture index](./index.md) — the full source-status table.
- [Source / Device / Stream](../concepts/source-device-stream.md) — the identity model the envelope uses.
- Root [`README.md`](../../README.md) and [`API.md`](../../API.md) — overview and the wire contract.
