# Scientific Product Execution Plan

This plan turns HealthSave Observatory from an evidence-linked dashboard into a
trustworthy quantified-self loop: **observe -> explain -> test -> evaluate ->
decide -> learn**. It is an implementation sequence, not a promise of release
dates. Each packet must be independently releasable and committed separately.

## Product principles

1. **Incomplete evidence never looks complete.** Composite scores, findings, and
   comparisons expose input completeness, coverage, and limitations beside the
   conclusion.
2. **Time has an explicit meaning.** Calendar days, sleep days, experiment days,
   and chart alignment use a documented person-local time model.
3. **Association is not intervention evidence.** Observational, repeated-phase,
   and randomized results use distinct labels and claims.
4. **Missingness is evidence.** Source downtime, wear time, and unequal coverage
   can suppress or qualify a finding.
5. **Every recommendation has a receipt.** The user can inspect source, window,
   method, exclusions, uncertainty, and formula version.
6. **The LLM narrates; deterministic code computes.** Existing two-brain and
   egress boundaries remain unchanged.
7. **One question, one primary action.** UI structure follows user questions,
   not backend modules.

## Packet sequence

### S1 - Recovery evidence contract

**Goal:** stop incomplete recovery inputs from producing an authoritative score.

- Require at least three of five recovery inputs and at least one autonomic input
  (HRV or resting heart rate).
- Exclude missing inputs and renormalize the published weights over inputs that
  are actually present; never substitute a missing temperature with a perfect
  temperature score.
- Persist input count, available weight, evidence level, and formula version.
- Show completeness next to the recovery instrument and suppress legacy scores
  that do not meet the evidence contract.

**Acceptance:** pure mapping tests cover thin, partial, and complete inputs; old
thin findings render as “building”; web typecheck/tests/build and Python tests pass.

### S2 - Analytical time contract

**Goal:** make daily and circadian analysis person-local and reproducible.

- Add Observatory timezone and physiological-day boundary settings.
- Define sleep-day assignment and travel/timezone behavior.
- Apply the contract to daily aggregation, weekday/hour pivots, relationship
  alignment, and experiment calendars.
- Include timezone and day-boundary metadata in derived evidence.

**Acceptance:** DST, travel, midnight, and sleep-boundary fixtures pass; every
calendar-based analytical surface states its time basis.

### S3 - Timestamp-faithful chart grammar

**Goal:** remove visual alignment that the underlying timestamps do not support.

- Change multi-series inputs from value arrays to timestamped points.
- Render calendar overlays by actual time and phase comparisons by explicit
  normalized progress.
- Visualize gaps rather than connecting across missing intervals.
- Add accessible summaries and keyboard-readable point inspection.

**Acceptance:** irregular-frequency and missing-interval fixtures cannot render
as evenly aligned series; mobile and reduced-motion checks pass.

### S4 - Context and data quality

**Goal:** make explanations and confounders observable.

- Add Moments for illness, travel, alcohol, medication/supplement changes, late
  meals, unusual training, stress, and custom notes.
- Add a unified timeline and annotation pins on signal/finding views.
- Compute expected-vs-observed coverage, source downtime, valid days, and
  unequal-coverage warnings.
- Feed relevant Moments and quality warnings into finding-card confounders.

**Acceptance:** Moments remain host-local, are auditable, and can qualify or
suppress findings without changing frozen ingest routes.

### S5 - Experiment Studio

**Goal:** replace one-click experiments with explicit, inspectable protocols.

- Add a review step for question, intervention, primary outcome, expected
  direction, schedule, adherence, confounders, and stopping conditions.
- Distinguish observational preview, repeated-phase comparison, and genuinely
  randomized n-of-1 designs.
- Support balanced/counterbalanced sequences and washout where appropriate.
- Add daily adherence and protocol-deviation check-ins.
- End every experiment with Adopt, Repeat, Modify, Reject, or Inconclusive.

**Acceptance:** no experiment starts without protocol confirmation; result claims
match assignment method; low adherence and protocol deviations remain visible.

### S6 - Relationship inference

**Goal:** improve hypothesis generation without creating a false-positive engine.

- Add lagged relationships over a bounded, physiology-aware lag set.
- Apply Benjamini-Hochberg false-discovery-rate correction by analysis family.
- Report tested-pair count, overlap, adjusted significance, effect size, and lag.
- Add sensitivity views excluding illness, travel, and low-coverage days.

**Acceptance:** exploratory and confirmatory evidence are visibly distinct;
automatic breadth cannot ship without multiple-testing correction.

### S7 - Question-led information architecture

**Goal:** reduce tool fragmentation while preserving power-user capability.

- Daily: Today, Briefs, Experiments.
- Investigate: Signals, Relationships, Timeline.
- System: Sources & Routes, Privacy & Intelligence, Settings.
- Consolidate Data, Library, Explore, and Compare as contextual Signal workflows.
- Make Live, Empty, Unreachable, Demo, and Mixed Preview global, unmistakable states.
- Increase meaningful secondary text to a readable size; scientific caveats are
  not visually hidden.

**Acceptance:** core tasks require fewer navigation decisions; no live-empty state
silently substitutes demo data; all existing deep links receive redirects.

### S8 - Personal knowledge ledger

**Goal:** turn completed investigations into durable personal learning.

- Promote experiment decisions into versioned personal conclusions.
- Preserve supporting findings, experiments, conditions, confidence, and review date.
- Surface contradictions and replication history instead of overwriting conclusions.
- Use the ledger in Body Briefs and the private agent surface.

**Acceptance:** every conclusion links to evidence and can be revised without
losing history; no conclusion is generated solely by an LLM.

## Delivery and commit discipline

For every packet:

1. Start from a clean scoped tree and leave unrelated files untouched.
2. Add or update tests before changing behavior where practical.
3. Keep additive v2/API and database changes separate from UI changes.
4. Regenerate contract artifacts only at their documented owner; confirm v1 is
   byte-identical for v2-only work.
5. Commit one logical slice at a time with explicit paths; never use `git add -A`.
6. Run `ruff check . && python -m pytest -q` for backend work,
   `bun run typecheck && bun test app/ && bun run build` for web work, and the
   workspace `make trust-fast` after every meaningful completed slice.
7. A local schema-gate skip is not a pass. Route/schema changes use the pinned
   Docker regeneration path or are explicitly deferred to CI.
8. No deployment or push is part of these packets without explicit approval.

## Outcome metrics

- Time from first sync to first valid baseline and first evidence-qualified finding.
- Percentage of findings with sufficient and comparable coverage.
- Experiments started, completed, adherence-qualified, and ending in an explicit decision.
- Percentage of conclusions replicated or revised with new evidence.
- Users with at least one evidence-backed personal conclusion reviewed in 30 days.
