# The Private Body Observatory

HealthSave Observatory is a self-hosted backend for one thing: a single,
private, owned, longitudinal record of your body's data — and a place that
actually tells you something about it.

Most of us already generate a remarkable amount of body data. A watch counts
heart beats and sleep stages, a strap tracks recovery and strain, a phone logs
steps and workouts. But that data lives scattered across a handful of vendor
clouds, each showing you its own slice through its own app, none of them yours
to keep, query, or reason over as a whole. HealthSave Observatory inverts that:
**your data comes home, into one canonical record on hardware you control, and
the analysis runs there too.**

## What it is

An *observatory* is somewhere you go to look carefully at something over time.
That is the whole product. It is not a coaching app, not a cloud service that
holds your data, and not a feed of motivational nudges. It is the instrument and
the record:

- **One record.** Every source — Apple Health, wearables, file imports, future
  webhooks — normalizes into a single canonical store you own.
- **Longitudinal.** The value is in the history. Today only means something
  against your own months of baseline.
- **Private and owned.** The entire stack runs in a container on your hardware.
  Nothing phones home. Raw data does not leave your host unless you explicitly
  send it somewhere.

## The loop

The Observatory works as a repeating loop, and every stage is designed to be
honest about what it does and does not know:

1. **Capture.** Body data flows in from any connected source. Apple Health is
   supported today, via the [HealthSave](https://apps.apple.com/app/id6759843047)
   iOS app; more sources (Android Health Connect, generic webhooks) are planned.
2. **Canonical record.** Each incoming reading becomes a source-tagged
   observation in one canonical store. Raw data is preserved exactly as it
   arrived — nothing is overwritten or thrown away at ingest. See
   [Canonical Observations](canonical-observations.md).
3. **Today vs baseline.** The Observatory surface shows you today's numbers
   against your own personal baseline: what changed, by how much, and how
   complete the underlying data is.
4. **Evidence-linked findings.** A deterministic statistical engine computes
   structured findings — each tied to the specific observations and baseline
   window behind it. Findings are calculated, not improvised.
5. **The Body Brief.** Those findings are assembled into a periodic briefing —
   a clear, narrated summary of what your body has been doing — with each claim
   showing its evidence and its limits. (The productized weekly Body Brief is in
   progress; see the [Roadmap](../roadmap.md).)
6. **Investigate / route.** From a finding you can dig deeper into the raw
   history, query it from your own scripts and notebooks, or route it onward to
   tools you already run (Home Assistant, Grafana, a webhook), always behind a
   boundary you control. See [Privacy & Egress](privacy-and-egress.md).

The defining choice is the order: **measure deterministically first, narrate
second.** Findings come from statistics over your real history. A language model
may put those findings into words, but it never invents or judges them.

## Who it's for

The Observatory is built first for people who want their own body data under
their own roof:

- **Self-hosters and home-lab owners** who already run their own services and
  want their health data to be one more thing they own, not rent.
- **The quantified-self minded** who wear two or three devices and want them
  reconciled into one coherent record instead of three disconnected apps.
- **Builders** who want a private, queryable health API to plug into their own
  scripts, dashboards, notebooks, and agents.
- **The privacy-conscious** who are unwilling to hand a continuous stream of
  intimate biometrics to a vendor cloud, but still want real analysis.

## Why owned and self-hosted matters

Body data is among the most sensitive data you generate, and it is most useful
in aggregate and over time — exactly the shape that vendor silos discourage and
that a third party would most like to monetize. Self-hosting changes the deal:

- **It is genuinely yours.** One record, in standard storage you can query with
  plain SQL, that you can back up, move, and keep for as long as you like.
- **No silent lock-in or shutdown risk.** A connected service can change terms,
  raise prices, or disappear; a record on your hardware does not.
- **The trust boundary is real and auditable.** Because the analysis runs
  locally, the default is that nothing leaves. Any path off your host is
  explicit, opt-in, and inspectable — not a default you have to discover later.

The result is the inversion HealthSave Observatory is built around: your health
data is yours, unified, provenance-tracked, and ready for whatever intelligence
*you* choose to bring to it.

---

See also: [Source / Device / Stream](source-device-stream.md) ·
[Canonical Observations](canonical-observations.md) ·
[Privacy & Egress](privacy-and-egress.md) · [Roadmap](../roadmap.md) ·
[project README](../../README.md)
