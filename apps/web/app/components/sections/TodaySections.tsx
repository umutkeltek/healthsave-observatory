// The Today page, split into independently-streamed async sections. Each
// fetches its own data (hot reads are cache()-deduped in lib/load.ts) inside
// its own Suspense boundary in app/page.tsx — the slowest read no longer
// gates the first byte. Every section degrades to null/empty exactly like the
// old monolithic page: hasAnyData() is cached, so the empty-state verdict is
// consistent across sections within one request.

import { type Finding, isNarratorOff, type Privacy, type Readiness } from "../../lib/api";
import {
  agoLabel,
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
import { getPinnedMetrics } from "../../lib/prefs";
import { EvidenceCard } from "../EvidenceCard";
import { ExperimentsCard } from "../ExperimentsCard";
import { LocalVaultReceipt, type VaultStep } from "../LocalVaultReceipt";
import { MetricCard } from "../MetricCard";
import { ReadinessCard } from "../ReadinessCard";
import { RecoveryHero } from "../RecoveryHero";
import { SleepCard } from "../SleepCard";
import { WeeklyBriefCard } from "../WeeklyBriefCard";

// The recovery score rides the findings stream (analysis writes a
// `recovery_score` finding with structured_data.score). Absent until the engine
// has computed one — the hero degrades gracefully when it's missing.
function recoveryScore(findings: Finding[] | null): number | null {
  const found = findings?.find((f) => f.finding_type === "recovery_score");
  const score = found?.structured_data?.score;
  return typeof score === "number" && Number.isFinite(score) ? Math.round(score) : null;
}

// Lead line for the hero: the briefing's first sentence (the local LLM's voice),
// falling back to the weekly summary, then to an honest data-state line.
function heroHeadline(
  briefing: string | null | undefined,
  weekly: string | null | undefined,
  findingCount: number,
): string {
  const first = (text?: string | null): string | null => {
    if (!text) return null;
    const t = text.trim();
    const dot = t.indexOf(". ");
    return dot > 0 ? t.slice(0, dot + 1) : t.slice(0, 180);
  };
  return (
    first(briefing) ??
    first(weekly) ??
    (findingCount > 0
      ? `${findingCount} signal${findingCount > 1 ? "s" : ""} from your latest analysis — the evidence is below.`
      : "Your data is flowing. First insights appear as your baselines build.")
  );
}

// Privacy posture rendered as a chain of custody, from the live egress policy.
function vaultSteps(privacy: Privacy | null, readiness: Readiness | null): VaultStep[] {
  const source = readiness?.sources?.[0]?.source_plugin_id ?? "Source";
  const totalRows = (readiness?.sources ?? []).reduce((n, s) => n + (s.observation_count ?? 0), 0);
  const provider = privacy?.provider ?? "ollama";
  const local = privacy?.is_local ?? true;
  const cloudActive = privacy?.cloud_active ?? false;
  const narratorOff = isNarratorOff(privacy?.provider);
  return [
    { label: `${source} → ingest`, meta: agoLabel(readiness?.last_ingested_at) },
    { label: "TimescaleDB", meta: totalRows ? `${totalRows.toLocaleString()} rows` : "local store" },
    { label: "Statistical engine", meta: "deterministic" },
    narratorOff
      ? { label: "LLM narrator", meta: "off — none" }
      : { label: `${provider} ${local ? "(local)" : "(cloud)"}`, meta: local ? "on-device" : "cloud" },
    { label: "Cloud egress", meta: cloudActive ? "active" : "blocked", blocked: !cloudActive },
  ];
}

function EmptyToday() {
  // Rendered inside .today-grid (the hero slot) — span the full grid so the
  // empty state doesn't get squeezed into one column.
  return (
    <section className="lead" style={{ gridColumn: "1 / -1" }}>
      <article className="hero">
        <div className="hero-eyebrow">Today</div>
        <p className="recovery-line" style={{ marginTop: 8 }}>
          No data yet. HealthSave Observatory turns your Apple Health + wearable data into a daily, private
          briefing — but it needs a day or so of readings first.
        </p>
        <div className="exp-action">
          <a className="btn" href="/demo">
            Explore the demo
          </a>
          <span className="empty">
            Or open <strong>HealthSave → Settings → Server Sync</strong>, point it at this server,
            and tap “Sync New Data.”
          </span>
        </div>
      </article>
    </section>
  );
}

export async function HeroSection() {
  if (!(await hasAnyData())) return <EmptyToday />;
  const [readiness, findings, latest, hrv] = await Promise.all([
    safeReadiness(),
    safeFindings(),
    safeLatest(),
    safeSeries("vital.hrv_sdnn", "30d"),
  ]);
  const ribbonValues = (hrv?.points ?? [])
    .map((p) => p.value)
    .filter((v): v is number => v !== null);
  const lastObs = readiness?.last_observation_at;
  const live = Boolean(lastObs && Date.now() - new Date(lastObs).getTime() < 24 * 3600_000);
  return (
    <RecoveryHero
      freshness={agoLabel(readiness?.last_observation_at)}
      live={live}
      score={recoveryScore(findings)}
      headline={heroHeadline(
        latest?.daily_briefing?.narrative,
        latest?.weekly_summary?.narrative,
        findings?.length ?? 0,
      )}
      ribbon={ribbonValues.length >= 2 ? { values: ribbonValues, axis: ["30 days ago", "today"] } : null}
    />
  );
}

export async function VaultSection() {
  if (!(await hasAnyData())) return null;
  const [privacy, readiness, receipts] = await Promise.all([
    safePrivacy(),
    safeReadiness(),
    safeReceipts(),
  ]);
  // Real chain-of-custody proof: the most recent egress-relevant config event.
  const lastEvent = receipts?.events?.[0];
  const auditNote = lastEvent
    ? `last config event: ${lastEvent.event_type} · ${agoLabel(lastEvent.created_at)}`
    : receipts?.events_unavailable
      ? "audit trail unavailable (backend predates migration 017)"
      : null;
  return (
    <div className="col-4">
      <LocalVaultReceipt steps={vaultSteps(privacy, readiness)} auditNote={auditNote} />
    </div>
  );
}

export async function InsightsSection() {
  if (!(await hasAnyData())) return null;
  const [latest, findings, privacy, narratives] = await Promise.all([
    safeLatest(),
    safeFindings(),
    safePrivacy(),
    safeNarratives(),
  ]);
  return (
    <div className="row-2">
      <WeeklyBriefCard
        latest={latest}
        narratorOff={isNarratorOff(privacy?.provider)}
        history={narratives ?? []}
      />
      <EvidenceCard findings={findings} />
    </div>
  );
}

export async function ExperimentsSection() {
  if (!(await hasAnyData())) return null;
  const [candidates, experiments] = await Promise.all([safeCandidates(), safeExperiments()]);
  return (
    <section className="lead">
      <ExperimentsCard experiments={experiments} candidates={candidates} />
    </section>
  );
}

export async function SignalsSection() {
  if (!(await hasAnyData())) return null;
  // Pinned metrics (Library star) replace the curated default grid.
  const pinned = await getPinnedMetrics();
  let defs: { id: string; title: string }[] = GRID_METRICS;
  if (pinned.length > 0) {
    const catalog = await safeMetrics();
    defs = pinned.map((id) => ({
      id,
      title: catalog?.find((m) => m.id === id)?.display_name ?? id,
    }));
  }
  const [map, sleep] = await Promise.all([
    safeSeriesMany(defs.map((d) => d.id), "7d"),
    safeSeries("sleep.stage", "7d"),
  ]);
  return (
    <>
      <div className="section-label">Signals{pinned.length > 0 ? " · pinned" : ""}</div>
      <section className="grid">
        {defs.map((metric) => (
          <MetricCard key={metric.id} series={map.get(metric.id) ?? null} fallbackTitle={metric.title} />
        ))}
        <SleepCard series={sleep} />
      </section>
    </>
  );
}

export async function ReadinessSection() {
  if (!(await hasAnyData())) return null;
  const readiness = await safeReadiness();
  const sparklines = await loadReadinessSparklines(readiness);
  return (
    <section className="lead">
      <ReadinessCard readiness={readiness} sparklines={sparklines} />
    </section>
  );
}
