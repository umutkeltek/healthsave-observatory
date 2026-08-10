import { type Finding, isNarratorOff, type MetricSeries, type Privacy, type Readiness } from "../../lib/api";
import {
  agoLabel,
  dataState,
  GRID_METRICS,
  hasAnyData,
  loadReadinessSparklines,
  safeCandidates,
  safeExperiments,
  safeFindings,
  safeLatest,
  safeMetrics,
  safeNarratives,
  safePrivacy,
  safeReadiness,
  safeReceipts,
  safeSeries,
  safeSeriesMany,
} from "../../lib/load";
import { recoveryEvidence } from "../../lib/findingPresentation";
import { getFocusGoal, getPinnedMetrics } from "../../lib/prefs";
import { EvidenceCard } from "../EvidenceCard";
import { ExperimentsCard } from "../ExperimentsCard";
import { FocusGoalPicker } from "../FocusGoalPicker";
import { GoalRibbon } from "../GoalRibbon";
import { LocalVaultReceipt, type VaultStep } from "../LocalVaultReceipt";
import { MetricCard } from "../MetricCard";
import { MobilityCard } from "../MobilityCard";
import { ReadinessCard } from "../ReadinessCard";
import { type BylineItem, RecoveryHero, type TodayHighlight } from "../RecoveryHero";
import { SleepCard } from "../SleepCard";
import { TodayPlumbing } from "../TodayPlumbing";
import { WeeklyBriefCard } from "../WeeklyBriefCard";

function recoveryFinding(findings: Finding[] | null): Finding | undefined {
  return findings?.find((finding) => finding.finding_type === "recovery_score");
}

function recoveryScore(findings: Finding[] | null): number | null {
  return recoveryEvidence(recoveryFinding(findings))?.score ?? null;
}

function recoveryCompleteness(findings: Finding[] | null): string | null {
  const evidence = recoveryEvidence(recoveryFinding(findings));
  return evidence ? `${evidence.inputCount}/${evidence.inputTotal} inputs` : null;
}

const CONTRIBUTOR_DEFS = [
  { key: "hrv_vs_baseline_pct", label: "HRV", unit: "%", positiveIsGood: true },
  { key: "rhr_vs_baseline_pct", label: "Resting HR", unit: "%", positiveIsGood: false },
  { key: "respiratory_rate_vs_baseline_pct", label: "Resp. rate", unit: "%", positiveIsGood: false },
  { key: "temperature_deviation_c", label: "Wrist temp", unit: "°C", positiveIsGood: false },
];

function recoveryContributors(findings: Finding[] | null) {
  const found = recoveryFinding(findings);
  if (!recoveryEvidence(found)) return [];
  const raw = found?.structured_data?.contributors as Record<string, unknown> | undefined;
  if (!raw) return [];
  return CONTRIBUTOR_DEFS.flatMap((def) => {
    const value = raw[def.key];
    return typeof value === "number" && Number.isFinite(value)
      ? [{ label: def.label, value, unit: def.unit, positiveIsGood: def.positiveIsGood }]
      : [];
  });
}

function recoveryDelta(findings: Finding[] | null): number | null {
  const found = recoveryFinding(findings);
  if (!recoveryEvidence(found)) return null;
  const delta = found?.structured_data?.delta_pct_vs_baseline;
  return typeof delta === "number" && Number.isFinite(delta) ? delta : null;
}

function readyMetricCount(readiness: Readiness | null): number {
  return (
    readiness?.metrics.filter((metric) =>
      Object.values(metric.analyzable ?? {}).some((gate) => gate.is_sufficient),
    ).length ?? 0
  );
}

function metricsWithData(readiness: Readiness | null): number {
  return (
    readiness?.summary.metrics_with_data ??
    readiness?.metrics.filter((metric) => metric.observation_count > 0).length ??
    0
  );
}

function changeCount(findings: Finding[] | null): number {
  return findings?.filter((finding) => finding.finding_type !== "recovery_score").length ?? 0;
}

function todaySummary(score: number | null, findings: Finding[] | null, readiness: Readiness | null): string {
  const ready = readyMetricCount(readiness);
  const changes = changeCount(findings);
  const readyLine = ready > 0 ? `${ready} signals have enough history.` : "Your baseline is still building.";

  if (score === null) {
    return `Your data is syncing. ${readyLine}`;
  }
  if (score >= 60) {
    return changes > 0
      ? `You look steady. The brief below shows what changed. ${readyLine}`
      : `You look steady. No major changes need attention. ${readyLine}`;
  }
  if (score >= 45) {
    return `Some signals are worth watching today. Start with the first change below. ${readyLine}`;
  }
  return `Recovery is low today. Focus on rest, sleep, and heart-rate signals first. ${readyLine}`;
}

function todayHighlights(readiness: Readiness | null, findings: Finding[] | null, live: boolean): TodayHighlight[] {
  return [
    {
      label: "Last sync",
      value: agoLabel(readiness?.last_observation_at),
      hint: live ? "recent readings" : "refresh soon",
      tone: live ? "good" : "watch",
    },
    {
      label: "Signals",
      value: metricsWithData(readiness).toLocaleString(),
      hint: "with data",
    },
    {
      label: "Ready",
      value: readyMetricCount(readiness).toLocaleString(),
      hint: "enough history",
    },
    {
      label: "Changes",
      value: changeCount(findings).toLocaleString(),
      hint: changeCount(findings) > 0 ? "review below" : "none flagged",
    },
  ];
}

// Byline for the hero lede — every atom is a fact the hero already holds
// (that the score is measured against the personal baseline, the ready-signal
// count, sync freshness). We deliberately do NOT print a "nights" count: the
// only window figure on hand is the raw HRV sample count (thousands of
// readings, not nights), so quoting it would be a misleading number.
function heroByline(readiness: Readiness | null, freshness: string): BylineItem[] {
  const items: BylineItem[] = [{ lead: "from ", strong: "your baseline" }];
  const ready = readyMetricCount(readiness);
  if (ready > 0) items.push({ strong: ready.toLocaleString(), trail: " signals ready" });
  items.push({ lead: "synced ", strong: freshness });
  return items;
}

function vaultSteps(privacy: Privacy | null, readiness: Readiness | null): VaultStep[] {
  const sourceCount = readiness?.sources?.length ?? 0;
  const totalRows = (readiness?.sources ?? []).reduce((n, s) => n + (s.observation_count ?? 0), 0);
  const provider = privacy?.provider ?? "ollama";
  const local = privacy?.is_local ?? true;
  const cloudActive = privacy?.cloud_active ?? false;
  const narratorOff = isNarratorOff(privacy?.provider);
  return [
    { label: "HealthSave sync", meta: sourceCount > 1 ? `${sourceCount} sources` : agoLabel(readiness?.last_ingested_at) },
    { label: "Local store", meta: totalRows ? `${totalRows.toLocaleString()} rows` : "ready" },
    { label: "Pattern checks", meta: "on this server" },
    narratorOff
      ? { label: "Briefs", meta: "off" }
      : { label: local ? "Private briefs" : "Cloud briefs", meta: local ? "local" : provider },
    { label: "Cloud sharing", meta: cloudActive ? "on" : "off", blocked: !cloudActive },
  ];
}

async function EmptyToday({ state }: { state: "empty" | "unreachable" }) {
  if (state === "unreachable") {
    return (
      <section className="lead">
        <article className="hero today-hero">
          <div className="hero-eyebrow">Today</div>
          <h2>Today could not load</h2>
          <p className="recovery-line" style={{ marginTop: 8 }}>
            Today loaded, but your Observatory data did not answer. Check the sync service or use the demo while
            it reconnects.
          </p>
          <div className="exp-action">
            <a className="btn" href="/demo">
              Explore demo
            </a>
          <span className="empty">The demo uses local sample data while your connection recovers.</span>
          </div>
        </article>
      </section>
    );
  }

  const goal = await getFocusGoal();
  return (
    <section className="lead">
      <article className="hero today-hero firstrun">
        <div className="hero-eyebrow">Welcome</div>
        <h2>Your private observatory is ready</h2>
        <p className="recovery-line" style={{ marginTop: 8 }}>
          Sync Apple Health from the app, then explore your data across three surfaces.
        </p>
        <ol className="firstrun-steps">
          <li className="firstrun-step">
            <span className="firstrun-n">1</span>
            <div>
              <strong>Pair HealthSave app.</strong>
              <span className="firstrun-hint">
                Open <strong>HealthSave → Settings → Server Sync</strong> on your phone and enter this server&apos;s URL.
              </span>
            </div>
          </li>
          <li className="firstrun-step">
            <span className="firstrun-n">2</span>
            <div>
              <strong>Explore the three pillars.</strong>
              <span className="firstrun-hint">
                <a href="/">Today</a> tracks recovery.{" "}
                <a href="/sleep">Sleep</a> shows your nights.{" "}
                <a href="/activity">Activity</a> measures daily strain.
              </span>
            </div>
          </li>
          <li className="firstrun-step">
            <span className="firstrun-n">3</span>
            <div>
              <strong>Try the demo.</strong>
              <span className="firstrun-hint">
                <a href="/demo">Explore demo</a> — a 30-day recovery story with real-looking data.
              </span>
            </div>
          </li>
          <li className="firstrun-step">
            <span className="firstrun-n">4</span>
            <div>
              <strong>Set your focus.</strong>
              <span className="firstrun-hint">
                {goal
                  ? `Working toward: ${goal.title}. Tap again to change or clear it.`
                  : "Pick what you are working toward. Today will orient around it."}
              </span>
              <FocusGoalPicker active={goal} />
            </div>
          </li>
        </ol>
      </article>
    </section>
  );
}

async function gridDefs(): Promise<{ defs: { id: string; title: string }[]; pinned: boolean }> {
  const pinned = await getPinnedMetrics();
  if (pinned.length === 0) return { defs: GRID_METRICS, pinned: false };
  const catalog = await safeMetrics();
  return {
    defs: pinned.map((id) => ({
      id,
      title: catalog?.find((m) => m.id === id)?.display_name ?? id,
    })),
    pinned: true,
  };
}

async function todaySeries7d() {
  const [{ defs }, goal] = await Promise.all([gridDefs(), getFocusGoal()]);
  const ids = defs.map((d) => d.id);
  const seen = new Set(ids);
  for (const id of goal?.metricIds ?? []) {
    if (!seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return safeSeriesMany(ids, "7d");
}

export async function GoalSection() {
  if (!(await hasAnyData())) return null;
  const goal = await getFocusGoal();
  if (!goal) return null;
  const seriesById = await todaySeries7d();
  return <GoalRibbon goal={goal} seriesById={seriesById} />;
}

export async function HeroSection() {
  const state = await dataState();
  if (state !== "data") return <EmptyToday state={state} />;

  const [readiness, findings, hrv] = await Promise.all([
    safeReadiness(),
    safeFindings(),
    safeSeries("vital.hrv_sdnn", "30d"),
  ]);
  const ribbonValues = (hrv?.points ?? []).map((p) => p.value).filter((v): v is number => v !== null);
  const lastObs = readiness?.last_observation_at;
  const live = Boolean(lastObs && Date.now() - new Date(lastObs).getTime() < 24 * 3600_000);
  const score = recoveryScore(findings);
  const freshness = agoLabel(readiness?.last_observation_at);

  return (
    <>
      <RecoveryHero
        freshness={freshness}
        live={live}
        score={score}
        contributors={recoveryContributors(findings)}
        summary={todaySummary(score, findings, readiness)}
        byline={heroByline(readiness, freshness)}
        deltaPct={recoveryDelta(findings)}
        evidenceLabel={recoveryCompleteness(findings)}
        ribbon={ribbonValues.length >= 2 ? { values: ribbonValues, axis: ["30 days ago", "today"] } : null}
      />
      <TodayPlumbing highlights={todayHighlights(readiness, findings, live)} live={live} />
    </>
  );
}

export async function VaultSection() {
  if (!(await hasAnyData())) return null;
  const [privacy, readiness, receipts] = await Promise.all([safePrivacy(), safeReadiness(), safeReceipts()]);
  const cloudActive = privacy?.cloud_active ?? false;
  const lastEvent = receipts?.events?.[0];
  const auditNote = lastEvent
    ? `Privacy setting changed - ${agoLabel(lastEvent.created_at)}`
    : receipts?.events_unavailable
      ? "Privacy history is still being prepared"
      : null;

  return (
    <LocalVaultReceipt
      steps={vaultSteps(privacy, readiness)}
      title={cloudActive ? "Data sharing" : "Data privacy"}
      seal={cloudActive ? "Cloud briefs on" : "Stays local"}
      variant={cloudActive ? "egress" : "local"}
      auditNote={auditNote}
    />
  );
}

export async function TodayStorySection() {
  if (!(await hasAnyData())) return null;
  const [latest, findings, privacy, narratives, candidates, experiments] = await Promise.all([
    safeLatest(),
    safeFindings(),
    safePrivacy(),
    safeNarratives(),
    safeCandidates(),
    safeExperiments(),
  ]);
  return (
    <section className="today-story-grid" aria-label="Today summary and changes">
      <div className="today-story-left">
        <WeeklyBriefCard latest={latest} narratorOff={isNarratorOff(privacy?.provider)} history={narratives ?? []} />
        <ExperimentsCard experiments={experiments} candidates={candidates} />
      </div>
      <EvidenceCard findings={findings} compact />
    </section>
  );
}

export async function SignalsSection() {
  if (!(await hasAnyData())) return null;
  const [{ defs: baseDefs, pinned }, goal] = await Promise.all([gridDefs(), getFocusGoal()]);
  let defs = baseDefs;
  if (goal) {
    const goalSet = new Set(goal.metricIds);
    defs = [...defs.filter((d) => goalSet.has(d.id)), ...defs.filter((d) => !goalSet.has(d.id))];
  }
  // Pull both the metric grid series and the dedicated mobility-card series in
  // one batch — fewer round-trips to the backend per Today page render.
  const mobilityIds = [
    "vital.walking_heart_rate_average",
    "mobility.walking_speed",
    "mobility.walking_step_length",
    "mobility.walking_asymmetry",
  ];
  const [map, sleep, mobility] = await Promise.all([
    todaySeries7d(),
    safeSeries("sleep.stage", "7d"),
    safeSeriesMany(mobilityIds, "7d"),
  ]);
  const mobilitySeries: Record<string, MetricSeries | null> = {
    "vital.walking_heart_rate_average": mobility.get("vital.walking_heart_rate_average") ?? null,
    "mobility.walking_speed": mobility.get("mobility.walking_speed") ?? null,
    "mobility.walking_step_length": mobility.get("mobility.walking_step_length") ?? null,
    "mobility.walking_asymmetry": mobility.get("mobility.walking_asymmetry") ?? null,
  };
  return (
    <>
      <div className="section-label">Signals{pinned ? " - pinned" : ""}</div>
      <section className="grid today-signals-grid">
        {defs.map((metric) => (
          <MetricCard key={metric.id} series={map.get(metric.id) ?? null} fallbackTitle={metric.title} />
        ))}
        <SleepCard series={sleep} />
        <MobilityCard seriesByMetric={mobilitySeries} />
      </section>
    </>
  );
}

export async function ReadinessSection() {
  if (!(await hasAnyData())) return null;
  const readiness = await safeReadiness();
  const sparklines = await loadReadinessSparklines(readiness);
  return <ReadinessCard readiness={readiness} sparklines={sparklines} compact />;
}
