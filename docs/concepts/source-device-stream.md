# Source, Device, Stream

To keep one trustworthy record out of many devices, HealthSave Observatory needs
a precise answer to a deceptively hard question: *where did this number actually
come from?* The answer is a three-part identity model — **Source**, **Device**,
and **Stream** — that every observation is tagged with.

This page explains the model in plain terms. If you have ever seen a health
dashboard double-count your steps, or quietly merge two devices into one line
and lose the truth in the middle, this is the part that prevents it.

## The three parts

**Source — the integration.** A Source is *how* the data got in: an account or
connector. Apple Health (via the HealthSave app) is a Source. A direct wearable
connector is a Source. A future webhook or file importer is a Source. The Source
answers "which integration delivered this."

**Device — the emitter.** A Device is the actual thing that produced the reading:
a specific watch, a specific strap, a specific scale, a phone. Two different
watches are two different Devices even if they reach the Observatory through the
same Source. The Device answers "which physical hardware measured this."

**Stream — the stable join.** A Stream is one continuous line of a particular
metric from a particular Device through a particular Source — for example,
"resting heart rate, from *this* watch, via Apple Health." The Stream is the
stable identity that ties together every reading that genuinely belongs to the
same ongoing series. It has a durable identifier that persists with each
observation, so the same series stays the same series over months and across
re-syncs. The Stream answers "which ongoing line of measurement is this part
of."

Put simply: **Source is the pipe, Device is the instrument, and Stream is the
specific line you can chart without ambiguity.**

## Why this prevents broken dashboards

Health data is messy in a very particular way. The same metric arrives from
multiple devices; the same reading sometimes arrives twice through different
paths; a vendor sends both raw components and a pre-summed total. Without a
stable identity model, the usual outcomes are:

- **Double counting.** Two devices reporting steps get summed on top of an
  already-summed total, and your day looks twice as active as it was.
- **Broken charts.** A series gets reassigned to a new internal id after a
  re-sync, and a clean line turns into two jagged half-lines with a gap.
- **Messy dedupe.** Naive deduplication collapses two genuinely different
  readings just because they share a timestamp and a value.

Stream identity fixes all three. Because every reading carries its Source,
Device, and Stream, the Observatory knows exactly which line it belongs to. It
can deduplicate *within* a Stream (the same reading arriving twice) without ever
merging *across* Streams (two real readings that happen to coincide). A heart
rate of 72 bpm at 10:00 from your watch and 72 bpm at 10:00 from a separate strap
are two real observations on two Streams — and they stay two observations.

## Making source conflict visible

The most valuable consequence of this model is what it does when your devices
*disagree*.

Say your Apple Watch and your Whoop strap both report last night's sleep, and
they don't match — different total, different stages, different wake count. A
typical app silently picks one, or averages them, and shows you a single
confident number that is quietly fictional.

HealthSave Observatory does the opposite. **Both readings are kept, each tagged
to its own Stream, and the disagreement itself is something you can see.** When
you ask for "last night's sleep," you can look at the reconciled view, or you can
look at each source side by side and judge for yourself. The Observatory never
manufactures a single fake truth by destroying the evidence.

This is only possible because identity is captured at ingest and the raw readings
are never overwritten — the conflict is preserved as data, not papered over. How
that reconciliation works at read time is covered in
[Canonical Observations](canonical-observations.md).

## What this gives you

- **Charts that stay coherent** across re-syncs, device swaps, and overlapping
  sources.
- **Honest totals** — no accidental double counting from summing things that
  were already summed.
- **Visible provenance** — every number on screen can tell you which Source and
  Device produced it.
- **Real reconciliation** — when sources disagree, you see the disagreement and
  decide, instead of being handed a guess.

---

See also: [The Private Body Observatory](private-body-observatory.md) ·
[Canonical Observations](canonical-observations.md) ·
[Privacy & Egress](privacy-and-egress.md) · [project README](../../README.md)
