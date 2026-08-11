# Experiment Lab — Move #1 Design Sketch

> Status: design discussion (not yet a plan to execute). Reframes the first
> web UI from "anomaly inbox" to "self-experiment lab bench." Grounded in the
> existing v2 contracts (`packages/py/contracts/`) and storage schema (`db/schema.sql`).

## Thesis

The daily briefing is the funnel; the **n-of-1 experiment is the product**. The
inbox is the skeleton, the experiment is the heart. Move #1 ships the web UI
organized around experiments, with **one experiment type working end-to-end with
real statistical honesty** — not a hollow shell.

Audience: self-hosted quantified-self + biohackers. Non-negotiable: **glass box**
(every claim shows its evidence + uncertainty) and **adjustable agent loudness**
(graduated autonomy via the existing `decided_by: user | policy | auto`).

---

## 0. Surface decision (after auditing the HealthSave iOS repo)

The HealthSave iOS app (`healthsave/ios_app/`) is mature (v1.5, App Store live,
Pro paywall, 4-tab SwiftUI, ~20-language localized) but **push-only**: its entire
endpoint set is `/api/apple/batch`, `/api/apple/status`, `/api/health`,
`/api/v2/sync/runs/latest`. It never pulls the server's analysis — Dashboard/Trends
are computed on-device from HealthKit. Two consequences:

- Making it the experiment client requires a **net-new read-side API client** +
  notification actions, not just views.
- It **iterates slowly** (App Store review + heavy localization + reviewer preflight).

**Therefore, split the surface by phase:**

| Phase | Surface | Why |
|---|---|---|
| **Validation (audience = you)** | **CLI (writes) + Grafana (reads) + server engine** | Already exists. Zero new UI. Prove the statistics are honest on your own ABAB data before any consumer build. |
| **Consumer product** | **HealthSave iOS** — generated Swift client (from existing OpenAPI), one new tab, notification-action adherence | Daily 1-tap adherence + native result charts are phone-shaped; iOS does them best. Earns its slow release cadence *because the design is already settled*. |
| **Later (managed cloud / any device)** | `apps/web` Next.js | The "works without an app install" surface — matters for cloud, not for a self-host biohacker who already has HealthSave. |

**Open question to confirm first:** two backends exist — `products/health-data-hub`
(public OSS) and `healthsave/datahub` ("HealthSave-compatible reference backend").
Confirm which is canonical for the experiment engine before building.

## 1. Screen architecture — "The Bench" (consumer phase, iOS)

```
┌─────────────────────────────────────────────────────────────────────┐
│  THE BENCH (home)                                   ⚙ loudness  🔒 LLM │
├───────────────────────────────┬───────────────────────────────────────┤
│  ACTIVE EXPERIMENTS            │  AWAITING YOU (proposal inbox)         │
│  ┌──────────────────────────┐ │  ┌─────────────────────────────────┐  │
│  │ Caffeine cutoff → sleep  │ │  │ ⚗ HYPOTHESIS                    │  │
│  │ ████████░░░░ Day 9/14    │ │  │ "Alcohol ↔ next-morning HRV"    │  │
│  │ trending + (not yet sig) │ │  │ corr −0.61 over 30d · conf 0.7  │  │
│  └──────────────────────────┘ │  │ [Test this] [Dismiss]           │  │
│                                │  └─────────────────────────────────┘  │
│  RECENT RESULTS                │  ┌─────────────────────────────────┐  │
│  ┌──────────────────────────┐ │  │ ⚠ ANOMALY                       │  │
│  │ ✓ Mg before bed → +12%   │ │  │ HRV ↓ 3 days running            │  │
│  │   deep sleep (p=.03)     │ │  │ [Notify me] [Ignore] [Auto ✓]   │  │
│  │   ↻ replicate            │ │  └─────────────────────────────────┘  │
│  └──────────────────────────┘ │                                        │
├───────────────────────────────┴───────────────────────────────────────┤
│  ACTIVITY FEED (AgentEvent SSE stream)  run_started · proposal_created… │
└─────────────────────────────────────────────────────────────────────┘
```

Surfaces:

| Surface | Maps to contract | Purpose |
|---|---|---|
| **The Bench** (home) | `AgentEvent` (SSE), `ActionProposal`, experiment list | One stream: in-flight experiments, proposals awaiting you, recent results |
| **Proposal detail** (glass box) | `ActionProposal` + `Claim`/`EvidenceRef`/`Uncertainty` | The evidence chain. Approve/Reject/Defer + "always auto-approve this kind" |
| **Experiment console** | NEW `Experiment` entity + `AgentArtifact(experiment_plan)` | Design → monitor → result. The heart. |
| **Explorer** | `Finding` (trend/anomaly/correlation), `Measurement` | Human-readable trends/correlations → "Test this" spawns an experiment |
| **Settings** | autonomy policies + LLM routing | Loudness slider, per-kind policies, local↔frontier toggle, sources |

### Adjustable loudness (the autonomy ladder)

One concept, five rungs — each maps to `ActionDecision.decided_by`:

```
Silent ──── On request ──── Notify ──── Suggest experiments ──── Autopilot
(observe)   (ask only)      (inbox)     (proactive proposals)    (per-kind auto)
   │            │              │                │                     │
   └─ no props  └─ user-pull   └─ user (default)└─ user               └─ policy/auto
```

Plus per-`action_kind` override (the `policy` layer): e.g. `notify = auto`,
`create_experiment = ask`. This is graduated trust: **earn it, then delegate it.**

### LLM-in-the-UI control (confirmed: yes)

Visible toggle, two modes, privacy explainer always shown:

- **Local only** — Ollama, nothing leaves the box. Default.
- **Escalate hard questions** — routine narration stays local; *hard reasoning*
  (borderline experiment result, "should I worry?") routes to a frontier model
  **sending the findings/result object, never raw measurements**. The
  finding↔raw-data split in your contracts makes this safe by construction.

---

## 2. One experiment, end-to-end

Worked example: **"Caffeine cutoff after 2pm → deep sleep + HRV."**

```
 HYPOTHESIS ORIGIN
   (a) Agent: correlation/trend Finding → ActionProposal(
         action_kind="create_experiment",
         payload={hypothesis, intervention, target_metrics, design})
   (b) User: "New experiment" from Explorer
        │
        ▼
 DECISION  ActionDecision(approved, decided_by=user)
        │
        ▼
 INSTANTIATE  ActionExecution → creates NEW Experiment record (status=scheduled)
        │
        ▼
 LIFECYCLE  (new analysis/experiments driver, on the scheduler/supervisor)
   ├─ baseline    (7d)  observe target metrics → per-user baseline distribution
   ├─ intervention(14d) user applies change; adherence logged (1-tap → Measurement
   │                    metric="experiment.adherence", source=manual)
   └─ washout     (opt) revert + confirm reversion
        │   (data flows in via normal ingestion — experiment just reads windows)
        ▼
 ANALYSIS  (new analysis/experiments/analyze.py — the rigor)
   ├─ baseline vs intervention windows of target series
   ├─ effect size (Hedges' g) + CI
   ├─ significance via permutation/randomization test (NOT naive t-test —
   │   daily HRV/sleep are autocorrelated; honest method or honest caveat)
   ├─ confound scan (anomalies / other interventions overlapping the window?)
   └─ → structured ExperimentResult
        │
        ▼
 NARRATION  HealthLLMClient.generate_insight(insight_type="experiment_result")
   → escalation point for local↔frontier router (findings only)
   → AgentArtifact(kind="narrative") with Claim[] + EvidenceRef[] + Uncertainty
        │
        ▼
 SURFACE  Experiment console → Result: verdict · effect · significance ·
          before/after distributions · confounds · confidence · [↻ replicate]
        │
        ▼
 MEMORY  result embedded into per-user history (RAG) → future experiments cite it
```

---

## 3. Data model gap

`create_experiment` is in the `ActionProposal` contract and `AgentArtifact.kind`
includes `experiment_plan` + `intervention_proposal` — but there is **no
first-class experiment entity** in `db/schema.sql`. Today an experiment can only
live as an artifact payload blob. That's insufficient for lifecycle + analysis.

Proposed (contracts-first: define in `packages/py/contracts/`, generate SQL/TS):

```
Experiment(WithOwnership)
  id · hypothesis · intervention_spec · target_metrics: list[str]
  design: {baseline_days, intervention_days, washout_days, kind: before_after|ABAB}
  status: draft|scheduled|baseline|intervention|washout|analyzing|complete|abandoned
  origin: proposal_id | "user"   · parent_experiment_id (for replications)
  created_at · started_at · ended_at

ExperimentResult(WithOwnership)
  experiment_id · target_metric · baseline_stats · intervention_stats
  effect_size · effect_ci · test_name · p_value · confidence
  confounds: list[...]  · narrative_artifact_id
```

**Design call:** model adherence as a `Measurement` (`metric="experiment.adherence"`,
manual source) rather than a bespoke table — keeps the "everything is a
measurement" philosophy and reuses ingestion/storage. Replication is just a new
Experiment with `parent_experiment_id` set.

---

## 4. Reuse vs net-new (leverage map)

**Reuse (already built):** proposal→decision→execution plane · Measurement store +
TimescaleDB · ingestion · `HealthLLMClient` · `AgentArtifact` contract · multi-tenant
`WithOwnership` · generated `packages/ts/api-client` · anomaly detector (real, 311 LOC).

**Net-new (the actual work in move #1):**
1. `apps/web` — Next.js app in the compose stack, consuming the generated TS client.
2. `Experiment` + `ExperimentResult` contracts → migration → storage port + adapter.
3. Experiment lifecycle driver (baseline→intervention→washout state machine).
4. **Experiment analysis math** — the rigor (effect size, permutation test,
   confound scan). *This is the hard part and it's not free.*
5. Experiment narration prompt + local↔frontier router on `HealthLLMClient`.
6. Adherence logging surface (1-tap).

---

## 5. Pressure test — where it breaks

| Risk | Severity | Mitigation |
|---|---|---|
| **Statistical honesty on autocorrelated time series** — naive t-test overstates significance; this audience will catch it | 🔴 highest | Permutation/randomization test; explicit n; "suggestive, not proof — replicate." Power comes from **replication**, not sample size. |
| **Confounding** in 2–3 weeks of real life (travel, illness, season) | 🔴 high | Honest "associated with" framing + automated confound scan. Support **ABAB / alternating** designs for daily-toggleable interventions (much stronger than before/after). |
| **Adherence** — unverified intervention = garbage result | 🟠 med-high | 1-tap daily log; infer where possible (bedtime from sleep onset). If logging rots, the result rots. |
| **Empty stats modules** — `correlations.py` is a stub, `baselines.py` is 21 LOC; experiment math leans on exactly what isn't built | 🟠 med-high | Accept that the analysis math is net-new; build it first within move #1. |
| **Feedback latency** — 21 days before payoff; user loses interest | 🟡 med | Show honest interim signal ("trending +, not yet conclusive"); seed fast experiments (caffeine→sleep shows in days). |
| **No experiment entity** — touches contract + migration + storage ports | 🟡 med | Contracts-first; one migration. Bounded. |

---

## 6. The one decision that gates the build

Before building: **what is the minimum statistically-honest experiment we ship
first?** Two viable answers:

- **A. Before/after, single intervention** (caffeine cutoff). Simpler to build and
  explain; weaker causally; needs the honesty framing to not embarrass us.
- **B. ABAB / alternating block** (e.g. magnesium on/off in randomized 3-day blocks).
  Harder UX (more switching), but **dramatically stronger inference** and far more
  credible to a sophisticated audience — arguably the only honest n-of-1.

Recommendation: **B for the flagship**, A as the gentle on-ramp. The credibility of
the whole "your body, scientifically" claim rests on getting the first one right.
