import { cache } from "react";
import Link from "next/link";
import { type Finding, isNarratorOff, type Privacy, type Readiness } from "../../lib/api";
import {
  agoLabel,
  dataState,
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
  safeStreams,
} from "../../lib/load";
import { recoveryEvidence } from "../../lib/findingPresentation";
import { getFocusGoal, getPinnedMetrics } from "../../lib/prefs";
import { TodayTrend } from "../TodayTrend";
import { friendlyName } from "../../lib/provenance";
import { hasOwnerDailyTotalSemantics } from "../../lib/series";
import { TodayFindings } from "../TodayFindings";
import { TodayMetricCard } from "../TodayMetricCard";
import { DEFAULT_TODAY_METRICS, recoveryRecency, findingEvidenceHref, dailyReadings, sleepDurationFromStages, todayReadings, type TodayTrendOption } from "../../lib/todayPresentation";
import { ExperimentsCard } from "../ExperimentsCard";
import { FocusGoalPicker } from "../FocusGoalPicker";
import { GoalRibbon } from "../GoalRibbon";
import { LocalVaultReceipt, type VaultStep } from "../LocalVaultReceipt";
import { ReadinessCard } from "../ReadinessCard";
import { RecoveryHero } from "../RecoveryHero";
import { WeeklyBriefCard } from "../WeeklyBriefCard";

function recoveryFinding(findings: Finding[] | null): Finding | undefined {
  return findings?.find((finding) => finding.finding_type === "recovery_score");
}

function recoveryScore(findings: Finding[] | null): number | null {
  return recoveryEvidence(recoveryFinding(findings))?.score ?? null;
}

function recoveryCompleteness(findings: Finding[] | null): string | null {
  const evidence = recoveryEvidence(recoveryFinding(findings));
  return evidence ? `${evidence.inputCount} of ${evidence.inputTotal} signals` : null;
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


function changeCount(findings: Finding[] | null): number {
  return findings?.filter((finding) => finding.finding_type !== "recovery_score").length ?? 0;
}

function todaySummary(score: number | null, findings: Finding[] | null, readiness: Readiness | null): string {
  const ready = readyMetricCount(readiness);
  const changes = changeCount(findings);
  const readyLine = ready > 0 ? `${ready} signals have enough history.` : "Your baseline is still building.";

  if (score === null) {
    return `Recovery is still building. ${readyLine}`;
  }
  if (score >= 60) {
    return changes > 0
      ? `You look steady. The findings below show what changed. ${readyLine}`
      : `You look steady. No major changes need attention. ${readyLine}`;
  }
  if (score >= 45) {
    return `Some signals are worth watching today. Start with the first change below. ${readyLine}`;
  }
  return `Recovery is low today. Focus on rest, sleep, and heart-rate signals first. ${readyLine}`;
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
  if (pinned.length === 0) return { defs: DEFAULT_TODAY_METRICS, pinned: false };
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

export async function HeroSection({ showSignals = true }: { showSignals?: boolean }) {
  const state = await dataState();
  if (state !== "data") return <EmptyToday state={state} />;

  const [readiness, findings] = await Promise.all([
    safeReadiness(),
    safeFindings(),
  ]);
  const lastObs = readiness?.last_observation_at;
  const live = Boolean(lastObs && Date.now() - new Date(lastObs).getTime() < 24 * 3600_000);
  const score = recoveryScore(findings);
  const freshness = agoLabel(readiness?.last_observation_at);
  const finding = recoveryFinding(findings);
  const recency = recoveryRecency(finding?.created_at);
  const summary = findings === null
    ? "Recovery could not load. You can still explore your recorded readings."
    : score !== null && recency !== "current"
      ? recency === "older"
        ? "Your last recovery estimate. This calculation is over 24 hours old. Explore your latest readings below."
        : "Recovery date unavailable. The date of this estimate could not be verified. Explore your latest readings below."
      : todaySummary(score, findings, readiness);

  return (
    <div className={`today-overview${showSignals ? "" : " today-overview-solo"}`}>
      <RecoveryHero
        freshness={freshness}
        live={live}
        score={score}
        contributors={recoveryContributors(findings)}
        summary={summary}
        recency={recency}
        computedAt={finding?.created_at}
        evidenceHref={finding ? findingEvidenceHref(finding.id) : undefined}
        unavailable={findings === null}
        byline={[{ lead: "Compared with ", strong: "your baseline" }]}
        deltaPct={recoveryDelta(findings)}
        evidenceLabel={recoveryCompleteness(findings)}
        ribbon={null}
      />
      {showSignals && <SignalsSection />}
    </div>
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

// Tiles and the explorer share one window and source selection. This also
// avoids fetching the same signals once per UI surface.
const todaySeries30d = cache(async () => {
  const { defs, pinned } = await gridDefs();
  const [series, stages] = await Promise.all([
    safeSeriesMany(defs.map((metric) => metric.id), "30d"),
    defs.some((metric) => metric.id === "sleep.duration") ? safeSeries("sleep.stage", "30d") : null,
  ]);
  const displayMap = new Map(series);
  if (defs.some((metric) => metric.id === "sleep.duration") && todayReadings(displayMap.get("sleep.duration") ?? null).length === 0) {
    const sleep = sleepDurationFromStages(stages);
    if (sleep) displayMap.set("sleep.duration", sleep);
  }
  return { defs, pinned, displayMap };
});

async function trendOptions(): Promise<TodayTrendOption[]> {
  const [{ defs, displayMap }, streams] = await Promise.all([todaySeries30d(), safeStreams()]);
  return defs.map(({ id, title }) => {
    const data = displayMap.get(id) ?? null;
    const readings = todayReadings(data);
    const latest = readings.at(-1);
    const dailyTotal = hasOwnerDailyTotalSemantics(readings);
    const reconciled = latest?.source_id === "reconciled-sleep";
    const stream = streams?.find((item) => item.id === latest?.stream_id);
    return {
      id, title, unit: id === "activity.steps" ? "steps" : data?.metric.canonical_unit ?? null,
      days: dailyReadings(readings), latestAt: latest?.t ?? null,
      kind: dailyTotal ? "daily-total" : reconciled ? "nightly" : "daily-median",
      source: dailyTotal ? "Daily totals across sources" : reconciled ? "Reconciled sleep stages" :
        stream ? stream.device_label ?? friendlyName(stream.source_plugin_id) : latest ? "One source selected · see full history for provenance" : "No source readings available",
    };
  });
}

export async function TodayStorySection() {
  if (!(await hasAnyData())) return null;
  const [latest, findings, privacy, narratives, candidates, experiments, trends] =
    await Promise.all([
      safeLatest(),
      safeFindings(),
      safePrivacy(),
      safeNarratives(),
      safeCandidates(),
      safeExperiments(),
      trendOptions(),
    ]);
  const hasBrief = Boolean(latest?.weekly_summary || latest?.daily_briefing);
  return (
    <>
      <section
        className="today-story-grid"
        aria-label="Trends and recent changes"
      >
        <TodayTrend options={trends} now={new Date().toISOString()} />
        <TodayFindings findings={findings} />
      </section>
      <div className="today-secondary">
        {hasBrief ? (
          <WeeklyBriefCard
            latest={latest}
            narratorOff={isNarratorOff(privacy?.provider)}
            history={narratives ?? []}
          />
        ) : (
          <details className="today-disclosure">
            <summary>
              Weekly brief
              <span>
                {isNarratorOff(privacy?.provider)
                  ? "Briefs are off"
                  : "Not available yet"}
              </span>
            </summary>
            <WeeklyBriefCard
              latest={latest}
              narratorOff={isNarratorOff(privacy?.provider)}
              history={narratives ?? []}
            />
          </details>
        )}
        <details className="today-disclosure">
          <summary>
            Experiments<span>Ideas & progress</span>
          </summary>
          <ExperimentsCard experiments={experiments} candidates={candidates} />
        </details>
      </div>
    </>
  );
}

export async function SignalsSection() {
  if (!(await hasAnyData())) return null;
  const [{ defs: baseDefs, pinned, displayMap }, goal] = await Promise.all([
    todaySeries30d(),
    getFocusGoal(),
  ]);
  let defs = baseDefs;
  if (goal) {
    const goalSet = new Set(goal.metricIds);
    defs = [
      ...defs.filter((d) => goalSet.has(d.id)),
      ...defs.filter((d) => !goalSet.has(d.id)),
    ];
  }
  return (
    <section
      className="today-signals"
      aria-label={pinned ? "Pinned readings" : "Your latest readings"}
    >
      <div className="today-section-heading">
        <h2>{pinned ? "Your pinned readings" : "Your latest readings"}</h2>
        <Link href="/library">
          All signals <span aria-hidden>↗</span>
        </Link>
      </div>
      <div className="today-signal-grid">
        {defs.slice(0, 6).map((metric) => (
          <TodayMetricCard
            key={metric.id}
            id={metric.id}
            title={metric.title}
            series={displayMap.get(metric.id) ?? null}
          />
        ))}
      </div>
      {defs.length > 6 && (
        <details className="today-more-signals">
          <summary>{defs.length - 6} more pinned readings</summary>
          <div className="today-signal-grid">
            {defs.slice(6).map((metric) => (
              <TodayMetricCard
                key={metric.id}
                id={metric.id}
                title={metric.title}
                series={displayMap.get(metric.id) ?? null}
              />
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

export async function ReadinessSection() {
  if (!(await hasAnyData())) return null;
  const readiness = await safeReadiness();
  const sparklines = await loadReadinessSparklines(readiness);
  return (
    <ReadinessCard readiness={readiness} sparklines={sparklines} compact />
  );
}
