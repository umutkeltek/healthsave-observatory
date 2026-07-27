import type { Metadata } from "next";

import { BaselineRibbon } from "../components/BaselineRibbon";
import { LocalVaultReceipt, type VaultStep } from "../components/LocalVaultReceipt";
import { ConsistencyGauge, Hypnogram, StageBreakdown } from "../components/SleepVisuals";
import { hasAnyData } from "../lib/load";
import {
  bedtimeDelta,
  bedtimeLabel,
  consistencyScore,
  durationLabel,
  sleepDebt,
  sleepTrends,
  type SleepNight,
  type SleepSegment,
} from "../lib/sleep";

// A seeded "first 60 seconds" Today - a believable 30-day story with one
// recovery dip, so a fresh clone (or the README screenshot) shows the product
// alive before any real data is synced. Pure fixtures; no API required.

export const revalidate = 30;
export const metadata: Metadata = { title: "Today · demo · HealthSave Observatory" };

// HRV (ms) over 30 days - steady, then a clear multi-day decline at the end.
const HRV_30D = [
  64, 61, 66, 63, 68, 62, 65, 67, 60, 63, 66, 64, 69, 62, 65, 63, 67, 61, 64, 66, 62, 60, 58, 55,
  52, 49, 47, 45, 44, 46,
];
const HRV_BAND: [number, number] = [55, 71];
const HRV_ANOMALIES = [27, 28];

const CONTRIBUTORS = [
  { name: "HRV", val: "−18%", pct: 78, dir: "down" as const },
  { name: "Resting HR", val: "+6 bpm", pct: 54, dir: "down" as const },
  { name: "Deep sleep", val: "−42 min", pct: 46, dir: "down" as const },
  { name: "Training load", val: "+31%", pct: 33, dir: "down" as const },
];

const VAULT: VaultStep[] = [
  { label: "Apple Watch → ingest", meta: "07:42" },
  { label: "TimescaleDB", meta: "1.42M rows" },
  { label: "Statistical engine", meta: "07:45" },
  { label: "Ollama · llama3.2 (local)", meta: "07:46" },
  { label: "Cloud egress", meta: "blocked", blocked: true },
];

const EVIDENCE = [
  {
    title: "HRV anomaly",
    calc: "42 ms vs expected 55-71 ms · z = −2.1",
    conf: "confidence high · source: Apple Watch",
  },
  {
    title: "Sleep architecture shift",
    calc: "deep sleep −42 min vs 30-day baseline",
    conf: "confidence moderate · source: Apple Watch",
  },
  {
    title: "Elevated training load",
    calc: "+31% vs baseline, two days ago",
    conf: "context · source: Workouts",
  },
];

// ─── Deterministic sleep demo data ──────────────────────────────────────
// Mulberry32 seeded PRNG so the demo renders identically on every clone.

function mulberry32(a: number): () => number {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function generateNight(
  dateStr: string,
  bedHour: number,
  bedMin: number,
  durationH: number,
  seed: number,
): SleepNight {
  const rng = mulberry32(seed);
  const segments: SleepSegment[] = [];
  const totalMin = Math.round(durationH * 60);
  const blockMin = 15; // each hypnogram bar = ~15 min of sleep
  const blockCount = Math.round(totalMin / blockMin);

  const baseTime = new Date(`${dateStr}T${String(bedHour).padStart(2, "0")}:${String(bedMin).padStart(2, "0")}:00Z`);

  for (let i = 0; i < blockCount; i++) {
    const pos = i / blockCount; // 0→1 through the night
    const t = new Date(baseTime.getTime() + i * blockMin * 60000);
    const r = rng();

    let stage: string;
    if (pos < 0.04) stage = r < 0.3 ? "awake" : "core";
    else if (pos < 0.48) stage = r < 0.55 ? "deep" : r < 0.12 ? "awake" : "core";
    else if (pos > 0.96) stage = r < 0.35 ? "awake" : "rem";
    else stage = r < 0.43 ? "rem" : r < 0.07 ? "awake" : "core";

    segments.push({ t: t.toISOString(), stage });
  }

  const stageMinutes: Record<string, number> = {};
  for (const seg of segments) stageMinutes[seg.stage] = (stageMinutes[seg.stage] || 0) + blockMin;

  const wakeTime = new Date(baseTime.getTime() + totalMin * 60000);

  return { date: dateStr, bedtime: baseTime.toISOString(), wakeTime: wakeTime.toISOString(), durationMin: totalMin, stageMinutes, segments };
}

// 7 nights: 6 healthy, 1 disrupted (night index 3 — late bed, short, fragmented)
const DEMO_SLEEP_NIGHTS: SleepNight[] = (() => {
  const raw = [
    generateNight("2026-07-20", 23, 5, 8.2, 100),
    generateNight("2026-07-21", 22, 55, 7.9, 200),
    generateNight("2026-07-22", 23, 10, 8.1, 300),
    generateNight("2026-07-23", 0, 45, 3.5, 400), // bad night
    generateNight("2026-07-24", 23, 0, 8.5, 500),
    generateNight("2026-07-25", 22, 50, 7.8, 600),
    generateNight("2026-07-26", 23, 15, 8.3, 700),
  ];
  return raw.sort((a, b) => a.date.localeCompare(b.date));
})();

// ─── Activity demo data ─────────────────────────────────────────────────

const DEMO_ACTIVITY = [
  { title: "Steps", value: 8450, avg: 7200, unit: "steps", icon: "👣" },
  { title: "Exercise", value: 62, avg: 45, unit: "min", icon: "🏃" },
  { title: "Active energy", value: 510, avg: 420, unit: "kcal", icon: "🔥" },
];

const DEMO_RHR = 58; // resting HR avg (bpm)
const DEMO_WALK_HR = 92; // walking HR avg (bpm)
const DEMO_STRAIN = Math.round(((DEMO_WALK_HR - DEMO_RHR) / DEMO_RHR) * 100); // ~58%

export default async function DemoToday() {
  // If the live backend already has data, the demo should be a courtesy, not
  // a trap: paint a thin banner at the top so the user can return to live.
  const live = await hasAnyData();

  // ─── Compute sleep demo metrics ───────────────────────────────────────
  const sleepTrend = sleepTrends(DEMO_SLEEP_NIGHTS);
  const lastNight = DEMO_SLEEP_NIGHTS[DEMO_SLEEP_NIGHTS.length - 1];
  const consistency = consistencyScore(sleepTrend);
  const debt = sleepDebt(sleepTrend);
  const { bedDelta, wakeDelta } = bedtimeDelta(sleepTrend);

  const durationValues = sleepTrend.durations;
  const sortedDurations = [...durationValues].sort((a, b) => a - b);
  const lastEfficiency = sleepTrend.efficiencies.length > 0
    ? sleepTrend.efficiencies[sleepTrend.efficiencies.length - 1]
    : null;
  const avgDuration = sortedDurations.length > 0
    ? Math.round(sortedDurations.reduce((a, b) => a + b) / sortedDurations.length)
    : 0;
  const hasShortNight = debt !== null && debt > 0;

  return (
    <>
      {live && (
        <div className="route-note demo-return" role="status">
          <span>Live data is available.</span>
          <a className="btn btn-ghost" href="/">
            Return to Today
          </a>
        </div>
      )}
      <div className="today-grid">
        <section className="hero col-8">
          <div className="hero-eyebrow">Today · this morning</div>
          <div className="recovery">
            <div className="recovery-score">63</div>
            <div className="recovery-state state-caution">Caution</div>
          </div>
          <p className="recovery-line">
            Below your baseline. <strong>Three independent signals agree</strong> - HRV is down,
            resting heart rate is up, and deep sleep fell.
          </p>
          <BaselineRibbon
            values={HRV_30D}
            band={HRV_BAND}
            anomalies={HRV_ANOMALIES}
            axis={["30 days ago", "today"]}
            live
          />
          <ul className="contribs">
            {CONTRIBUTORS.map((c) => (
              <li className="contrib" key={c.name}>
                <span className="contrib-name">{c.name}</span>
                <span className="contrib-track">
                  <span className={`contrib-fill ${c.dir}`} style={{ width: `${c.pct}%` }} />
                </span>
                <span className={`contrib-val ${c.dir}`}>{c.val}</span>
              </li>
            ))}
          </ul>
        </section>

        <div className="col-4">
          <LocalVaultReceipt steps={VAULT} />
        </div>

        <section className="card col-12">
          <div className="card-title">Evidence</div>
          <p className="empty" style={{ margin: "0 0 6px" }}>
            Every finding traces to a calculation - computed, not guessed.
          </p>
          <div>
            {EVIDENCE.map((e) => (
              <div className="ev-pin" key={e.title}>
                <span className="ev-dot" />
                <div className="ev-body">
                  <div className="ev-title">{e.title}</div>
                  <div className="ev-calc">{e.calc}</div>
                  <div className="ev-conf">{e.conf}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* ─── Sleep demo ──────────────────────────────────────────────── */}
      <div className="today-grid">
        <section className="card col-7">
          <div className="card-title">
            <span>Sleep · this week</span>
            <a href="/sleep" className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: "0.85rem" }}>
              See your sleep →
            </a>
          </div>
          <div className="sleep-hero-main">
            <div className="sleep-hero-lede">
              <h1>{durationLabel(lastNight.durationMin)}</h1>
              <p className="sleep-hero-meta">
                {bedtimeLabel(lastNight.bedtime)} → {bedtimeLabel(lastNight.wakeTime)}
                {(bedDelta != null || wakeDelta != null) && (
                  <span className="sleep-delta">
                    {" · "}
                    {bedDelta != null && `${bedDelta > 0 ? "+" : ""}${bedDelta} min bed`}
                    {bedDelta != null && wakeDelta != null && ", "}
                    {wakeDelta != null && `${wakeDelta > 0 ? "+" : ""}${wakeDelta} min wake`}
                    {" vs usual"}
                  </span>
                )}
              </p>
              <Hypnogram segments={lastNight.segments} />
            </div>
            <div className="sleep-hero-side">
              <StageBreakdown night={lastNight} />
            </div>
          </div>
          <div className="sleep-stats-row">
            <div className="sleep-stat-card">
              <span className="sleep-stat-label">Consistency</span>
              <ConsistencyGauge score={consistency} />
            </div>
            <div className="sleep-stat-card">
              <span className="sleep-stat-label">Sleep debt{hasShortNight ? " ⚠" : ""}</span>
              {debt !== null ? (
                <div className={`sleep-debt ${debt > 0 ? "warn" : "good"}`}>
                  <strong>{debt > 0 ? `+${debt}h` : "0h"}</strong>
                  <span>{debt > 0 ? "behind 8h target" : "on track"}</span>
                </div>
              ) : (
                <p className="empty">Need more data.</p>
              )}
            </div>
            <div className="sleep-stat-card">
              <span className="sleep-stat-label">Efficiency</span>
              {lastEfficiency !== null ? (
                <div className="sleep-debt good">
                  <strong>{Math.round(lastEfficiency)}%</strong>
                  <span>last night</span>
                </div>
              ) : (
                <p className="empty">No data.</p>
              )}
            </div>
            <div className="sleep-stat-card">
              <span className="sleep-stat-label">Avg duration</span>
              <div className="sleep-debt">
                <strong>{durationLabel(avgDuration)}</strong>
                <span>{sleepTrend.dates.length} nights</span>
              </div>
            </div>
          </div>
        </section>

        {/* ─── Activity demo ──────────────────────────────────────────── */}
        <section className="card col-5">
          <div className="card-title">
            <span>Activity · today</span>
            <a href="/activity" className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: "0.85rem" }}>
              See your activity →
            </a>
          </div>
          <div className="activity-grid" style={{ gridTemplateColumns: "1fr", gap: "10px" }}>
            {DEMO_ACTIVITY.map((card) => (
              <article key={card.title} className="card activity-card">
                <div className="activity-card-head">
                  <span className="activity-card-icon" aria-hidden>
                    {card.icon}
                  </span>
                  <h2>{card.title}</h2>
                </div>
                <div className="activity-card-value">
                  <span className="activity-big">{card.value.toLocaleString()}</span>
                  <span className="activity-unit">{card.unit}</span>
                </div>
                <div className="activity-card-foot mono">
                  <span>
                    7d avg <strong>{card.avg.toLocaleString()}</strong> {card.unit}
                  </span>
                </div>
              </article>
            ))}
          </div>
          <div className="activity-strain-card" style={{ marginTop: "10px", padding: "10px 0 0", borderTop: "1px solid var(--border)" }}>
            <div className={`activity-strain-value ${DEMO_STRAIN > 25 ? "up" : ""}`}>
              <strong>+{DEMO_STRAIN}%</strong>
              <span>walking HR above resting</span>
            </div>
            <div className="activity-strain-meta mono" style={{ marginTop: 4 }}>
              <span>Resting: {DEMO_RHR} bpm</span>
              <span>Walking: {DEMO_WALK_HR} bpm</span>
            </div>
          </div>
        </section>
      </div>

      <footer className="foot">demo data · a believable 30-day story · nothing left this host</footer>
    </>
  );
}
