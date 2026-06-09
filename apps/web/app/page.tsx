import { type Finding, isNarratorOff, type Privacy, type Readiness } from "./lib/api";
import { EvidenceCard } from "./components/EvidenceCard";
import { ExperimentsCard } from "./components/ExperimentsCard";
import { LocalVaultReceipt, type VaultStep } from "./components/LocalVaultReceipt";
import { MetricCard } from "./components/MetricCard";
import { ReadinessCard } from "./components/ReadinessCard";
import { RecoveryHero } from "./components/RecoveryHero";
import { SleepCard } from "./components/SleepCard";
import { WeeklyBriefCard } from "./components/WeeklyBriefCard";
import {
  agoLabel,
  GRID_METRICS,
  loadGrid,
  loadReadinessSparklines,
  safeCandidates,
  safeExperiments,
  safeFindings,
  safeLatest,
  safePrivacy,
  safeReadiness,
  safeSeries,
} from "./lib/load";

// Always render fresh — this is a live dashboard, not a static page.
export const dynamic = "force-dynamic";

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
  return (
    <section className="lead">
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

export default async function Home() {
  const readiness = await safeReadiness();
  const [latest, findings, candidates, experiments, privacy, sleep, gridSeries, sparklines, hrv] =
    await Promise.all([
      safeLatest(),
      safeFindings(),
      safeCandidates(),
      safeExperiments(),
      safePrivacy(),
      safeSeries("sleep.stage", "7d"),
      loadGrid(),
      loadReadinessSparklines(readiness),
      safeSeries("vital.hrv_sdnn", "30d"),
    ]);

  const hasData =
    (readiness?.metrics.length ?? 0) > 0 ||
    Boolean(latest?.daily_briefing) ||
    (findings?.length ?? 0) > 0;

  if (!hasData) {
    return (
      <>
        <EmptyToday />
        <footer className="foot">HealthSave Observatory · canonical observations · local-first</footer>
      </>
    );
  }

  const ribbonValues = (hrv?.points ?? [])
    .map((p) => p.value)
    .filter((v): v is number => v !== null);

  return (
    <>
      <div className="today-grid">
        <RecoveryHero
          freshness={agoLabel(readiness?.last_observation_at)}
          score={recoveryScore(findings)}
          headline={heroHeadline(
            latest?.daily_briefing?.narrative,
            latest?.weekly_summary?.narrative,
            findings?.length ?? 0,
          )}
          ribbon={ribbonValues.length >= 2 ? { values: ribbonValues, axis: ["30 days ago", "today"] } : null}
        />
        <div className="col-4">
          <LocalVaultReceipt steps={vaultSteps(privacy, readiness)} />
        </div>
      </div>

      <div className="row-2">
        <WeeklyBriefCard latest={latest} />
        <EvidenceCard findings={findings} />
      </div>

      <section className="lead">
        <ExperimentsCard experiments={experiments} candidates={candidates} />
      </section>

      <div className="section-label">Signals</div>
      <section className="grid">
        {GRID_METRICS.map((metric, index) => (
          <MetricCard key={metric.id} series={gridSeries[index]} fallbackTitle={metric.title} />
        ))}
        <SleepCard series={sleep} />
      </section>

      <section className="lead">
        <ReadinessCard readiness={readiness} sparklines={sparklines} />
      </section>

      <footer className="foot">HealthSave Observatory · canonical observations · local-first</footer>
    </>
  );
}
