# Canonical Observations

Underneath the Observatory dashboard and the Body Brief is one quiet, load-bearing
idea: **every reading from every source becomes the same kind of record — a
canonical, source-tagged observation.** This page explains what that record is
and why it is the contract that lets any source come in and any destination go
out without the whole system turning to spaghetti.

## One record type

A naïve health backend grows one table per metric and one ingestion path per
device. Heart rate gets its own shape, sleep gets another, a new wearable gets a
new column or a new table, and within a year the data model is a museum of
special cases that no two parts of the system read the same way.

HealthSave Observatory takes the opposite approach. There is **one canonical
observation** record, and everything — a heart-rate sample, a sleep session, a
step count, a body weight, a workout — is stored as an instance of it. Per-metric
views still exist for convenience and performance, but they are projections of
the canonical store, not separate truths. The canonical observation is the single
source of truth.

## Tagged values

Health metrics are not all the same shape. A heart rate is a single quantity. A
sleep session has stages and components. A workout is an event with a start and
an end. A flag like "atrial fibrillation detected" is a boolean. Some signals are
whole waveforms.

A single record type handles all of these through a **tagged value** — the
observation carries its value *together with* the kind of value it is (a
quantity, a category, a boolean, a set of components, an event, a waveform, and so
on). The reader always knows how to interpret the value because the value
announces its own type. New metric shapes can be added without inventing a new
table or breaking the readers that already exist.

## Source-tagged and provenance-tracked

Every canonical observation carries its full origin: the Source it came in
through, the Device that emitted it, and the Stream it belongs to (see
[Source / Device / Stream](source-device-stream.md)), along with the provenance
of how it was produced. This is what makes it possible to show, for any number on
screen, exactly where it came from — and to keep readings from different devices
distinct even when they describe the same metric at the same moment.

## Don't destroy raw at ingest — fuse at read

This is the principle the whole spine is built to protect:

> **Ingest is append-only and immutable. Reconciliation happens at read time, not
> at write time.**

When data arrives, the Observatory writes it down exactly as it came, tagged with
its identity, and never overwrites it. It does **not** try to merge, average, or
pick a winner at the moment of ingestion. That merging — the Observatory calls it
*fusion* — happens later, when you read.

Why it matters: the raw observations are the ground truth, and ground truth
should be preserved. Fusion rules are opinions, and opinions change. If you fused
at ingest, you would bake today's opinion into the permanent record and lose the
originals forever. By fusing at read instead:

- The raw, per-source readings are always recoverable.
- You can ask for the data different ways — one reconciled "best" line, every
  source kept separate, or a single chosen source — from the *same* underlying
  records.
- When sources disagree, the disagreement survives as data, so the Observatory
  can show it to you instead of hiding it (see
  [Source / Device / Stream](source-device-stream.md)).
- Improving how reconciliation works never requires rewriting history; it only
  changes how the same preserved records are read.

Derived metrics — things the Observatory computes from your data rather than
receives — re-enter the canonical store as observations too, tagged as computed
and carrying lineage back to what they were derived from. Computed results live
in the same spine as raw readings, with the same provenance discipline, so a
calculated number is just as inspectable as a measured one.

## The contract between any source in and any destination out

Because every reading is reduced to the same canonical, tagged, provenance-bearing
shape, the canonical observation becomes a **contract**:

- **Any source in.** Adding a new way to capture data — a new wearable connector,
  Android Health Connect, a generic webhook — only has to do one job: turn its
  readings into canonical observations. It does not need to know anything about
  the dashboard, the findings engine, or the routing layer.
- **Any destination out.** Anything that consumes data — the Observatory web
  surface, the statistical findings engine, your own scripts over the private
  API, a route to Home Assistant or a webhook — reads canonical observations. It
  does not need to know which device or integration originally produced them.

That decoupling is what keeps the system extensible. Sources and destinations
evolve independently on either side of one stable, well-defined record. The
canonical observation is the narrow waist that everything else hangs off.

---

See also: [The Private Body Observatory](private-body-observatory.md) ·
[Source / Device / Stream](source-device-stream.md) ·
[Privacy & Egress](privacy-and-egress.md) · [project README](../../README.md)
