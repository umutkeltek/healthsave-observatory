import type { Metadata } from "next";

import { BaselineRibbon } from "../components/BaselineRibbon";
import { LocalVaultReceipt, type VaultStep } from "../components/LocalVaultReceipt";

// A seeded "first 60 seconds" Today — a believable 30-day story with one
// recovery dip, so a fresh clone (or the README screenshot) shows the product
// alive before any real data is synced. Pure fixtures; no API required.

export const metadata: Metadata = { title: "Today · demo · HealthSave Observatory" };

// HRV (ms) over 30 days — steady, then a clear multi-day decline at the end.
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
    calc: "42 ms vs expected 55–71 ms · z = −2.1",
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

export default function DemoToday() {
  return (
    <>
      <div className="today-grid">
        <section className="hero col-8">
          <div className="hero-eyebrow">Today · this morning</div>
          <div className="recovery">
            <div className="recovery-score">63</div>
            <div className="recovery-state state-caution">Caution</div>
          </div>
          <p className="recovery-line">
            Below your baseline. <strong>Three independent signals agree</strong> — HRV is down,
            resting heart rate is up, and deep sleep fell.
          </p>
          <BaselineRibbon
            values={HRV_30D}
            band={HRV_BAND}
            anomalies={HRV_ANOMALIES}
            axis={["30 days ago", "today"]}
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
            Every finding traces to a calculation — computed, not guessed.
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

      <footer className="foot">demo data · a believable 30-day story · nothing left this host</footer>
    </>
  );
}
